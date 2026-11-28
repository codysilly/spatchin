// Local transactional model of a durable store. Never opens the private FAA database.
// Node 22 SQLite is experimental; this file is not a Cloudflare Worker or deployed adapter.
import { createHash } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { candidate, names, newer, verify } from './snapshot-relay-poc.mjs';
const CHUNK_BYTES=512*1024;
function validRelease(id, digest) {
  if (typeof id !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/.test(id) || typeof digest !== 'string' || !/^[a-f0-9]{64}$/.test(digest)) throw Error('Invalid release identity');
}
export class SqlitePublicationStore {
  constructor(file) {
    this.db=new DatabaseSync(file);
    this.db.exec(`PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;
      CREATE TABLE IF NOT EXISTS snapshots (slot TEXT, name TEXT, retrieved TEXT NOT NULL, sha TEXT NOT NULL, PRIMARY KEY(slot,name));
      CREATE TABLE IF NOT EXISTS chunks (slot TEXT,name TEXT,idx INTEGER,data BLOB NOT NULL,PRIMARY KEY(slot,name,idx),FOREIGN KEY(slot,name) REFERENCES snapshots(slot,name) ON DELETE CASCADE ON UPDATE CASCADE);
      CREATE TABLE IF NOT EXISTS releases (slot TEXT PRIMARY KEY,id TEXT NOT NULL,digest TEXT NOT NULL,manifest BLOB NOT NULL);`);
  }
  close(){this.db.close();}
  transaction(fn){
    this.db.exec('BEGIN IMMEDIATE');
    try { const result=fn();this.db.exec('COMMIT');return result; }
    catch(error){this.db.exec('ROLLBACK');throw error;}
  }
  get(slot,name,now){
    const row=this.db.prepare('SELECT retrieved,sha FROM snapshots WHERE slot=? AND name=?').get(slot,name);
    if(!row)return null;
    const chunks=this.db.prepare('SELECT idx,data FROM chunks WHERE slot=? AND name=? ORDER BY idx').all(slot,name);
    if(!chunks.length || chunks.some((chunk,i)=>chunk.idx!==i || !chunk.data.length || chunk.data.length>CHUNK_BYTES))throw Error('Invalid stored chunks');
    return verify(name,{name,retrieved:row.retrieved,sha256:row.sha,bytes:Buffer.concat(chunks.map(chunk=>Buffer.from(chunk.data))).toString('base64')},now);
  }
  put(slot,record,now){
    const name=record.name;
    const checked=verify(name,record,now),bytes=Buffer.from(checked.bytes,'base64');
    this.db.prepare('DELETE FROM snapshots WHERE slot=? AND name=?').run(slot,name);
    this.db.prepare('INSERT INTO snapshots VALUES(?,?,?,?)').run(slot,name,checked.retrieved,checked.sha256);
    const insert=this.db.prepare('INSERT INTO chunks VALUES(?,?,?,?)');
    for(let offset=0,index=0;offset<bytes.length;offset+=CHUNK_BYTES,index++)insert.run(slot,name,index,bytes.subarray(offset,offset+CHUNK_BYTES));
  }
  async accept(name,bytes,now){
    const next=candidate(name,bytes,now);
    return this.transaction(()=>{
      const old=this.get('latest',name,now);
      if(!newer(next,old))return false;
      if(old)this.put('prior',old,now);
      this.put('latest',next,now);return true;
    });
  }
  async read(name,now){
    if(!names.includes(name))throw Error('Unknown snapshot source');
    return this.transaction(()=>this.get('latest',name,now));
  }
  getRelease(slot){return this.db.prepare('SELECT id,digest FROM releases WHERE slot=?').get(slot)??null;}
  readSet(slot,now){
    return Object.fromEntries(names.map(name=>{
      const record=this.get(slot,name,now);
      if(!record)throw Error('Missing release snapshot');
      return [name,record];
    }));
  }
  status(now){return this.transaction(()=>({accepted:this.getRelease('accepted'),previous:this.getRelease('previous'),pending:this.getRelease('pending'),checkpoint:this.getRelease('accepted')?this.readSet('accepted',now):null}));}
  // Reserve the exact release before a deployment. Only one pending release at once.
  stage(id,manifestBytes,selected,now){
    if (!Buffer.isBuffer(manifestBytes) || manifestBytes.length>1024*1024) throw Error('Invalid release manifest bytes');
    const manifest=JSON.parse(manifestBytes.toString('utf8'));
    const digest=createHash('sha256').update(manifestBytes).digest('hex');
    validRelease(id,digest);
    if(manifest.schema!==1 || manifest.release!==id || !/^[a-f0-9]{40}$/.test(manifest.code_commit??'') || Object.keys(manifest.sources??{}).sort().join(',')!==[...names].sort().join(',')) throw Error('Invalid release manifest');
    return this.transaction(()=>{
      if(this.getRelease('pending'))throw Error('Unresolved pending release');
      const accepted=this.getRelease('accepted');
      if(accepted?.id===id || this.getRelease('previous')?.id===id)throw Error('Release ID already used');
      for(const name of names){
        const next=verify(name,selected[name],now),old=this.get('accepted',name,now);
        if(old)newer(next,old);
        if(manifest.sources[name].sha256!==next.sha256 || manifest.sources[name].retrieved!==next.retrieved || manifest.files?.find(file=>file.path===`data/${name}.json`)?.sha256!==next.sha256) throw Error('Manifest source digest or time mismatch');
        this.put('pending',next,now);
      }
      this.db.prepare('INSERT INTO releases VALUES(?,?,?,?)').run('pending',id,digest,manifestBytes);
    });
  }
  // Evidence is supplied by the future transport only after public manifest verification.
  // A crash before this call leaves pending intact. A conflicting digest cannot advance it.
  confirm(id,publicDigest,now){
    validRelease(id,publicDigest);
    return this.transaction(()=>{
      const pending=this.getRelease('pending');
      if(!pending || pending.id!==id || pending.digest!==publicDigest)throw Error('Public release digest mismatch');
      const data=this.readSet('pending',now);
      const accepted=this.getRelease('accepted');
      this.db.prepare("DELETE FROM snapshots WHERE slot='previous'").run();
      this.db.prepare("DELETE FROM releases WHERE slot='previous'").run();
      if(accepted){
        for(const name of names)newer(data[name],this.get('accepted',name,now));
        this.db.prepare("UPDATE snapshots SET slot='previous' WHERE slot='accepted'").run();
        this.db.prepare("UPDATE releases SET slot='previous' WHERE slot='accepted'").run();
      }
      this.db.prepare("UPDATE snapshots SET slot='accepted' WHERE slot='pending'").run();
      this.db.prepare("UPDATE releases SET slot='accepted' WHERE slot='pending'").run();
    });
  }
}
