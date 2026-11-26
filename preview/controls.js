/* Local preview state controls; no acquisition. */
import {mountDashboard} from '../app.js';
import {AirportCatalog,AirportMetadata} from '../airport-catalog.js';
import {NotamReader} from '../notam-reader.js';
import {SPATCHIN_SYNTHETIC_PREVIEW} from './fixtures.js';
const {render}=mountDashboard({AirportCatalog,AirportMetadata,NotamReader,preview:SPATCHIN_SYNTHETIC_PREVIEW});
document.getElementById('preview-state').addEventListener('change',event=>{
 const state=event.target.value;
 NotamReader.set(state==='unavailable'?null:SPATCHIN_SYNTHETIC_PREVIEW.notams,state==='error'?'NOTAM refresh failed; last snapshot retained':state==='stale'?'SYNTHETIC source reports STALE snapshot; retrieval time preserved. No age threshold applied.':null);
 render();
});
