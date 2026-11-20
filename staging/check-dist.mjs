// Verify explicit files and absence of private or unintended published content.
import { readdir, readFile } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
const dir=join(dirname(fileURLToPath(import.meta.url)),'dist');
const allowed=new Set([
 'index.html','styles.css','charcoal-dashboard.css','app.js','airport-catalog.js',
 'notam-reader.js','notam-snapshots.js','taf-reader.js','taf-timeline.js','scan.js','assets/branding/logo-cyan-magenta.svg',
 ...[16,32,64,128,180].map(n=>'assets/branding/logo-'+n+'.png')
]);
async function list(path='',out=[]){
 for(const entry of await readdir(join(dir,path),{withFileTypes:true})){
  const relative=join(path,entry.name).replaceAll('\\','/');
  if(entry.isDirectory())await list(relative,out);
  else if(entry.isFile())out.push(relative);
  else throw Error('Unexpected build entry: '+relative);
 }
 return out;
}
const actual=new Set(await list());
for(const p of allowed)if(!actual.has(p))throw Error('Missing static file: '+p);
for(const p of actual)if(!allowed.has(p))throw Error('Unapproved static file: '+p);
const html=await readFile(join(dir,'index.html'),'utf8');
if(!html.includes('<base href="/">')||html.includes('<base href="../">'))throw Error('Incorrect dashboard base path');
console.log('Verified private asset manifest:',actual.size,'allowlisted files');
