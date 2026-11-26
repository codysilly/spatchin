import {mountDashboard} from '../app.js';
import {NotamReader} from '../notam-reader.js';
import {NotamSnapshots} from '../notam-snapshots.js';
import {SPATCHIN_SYNTHETIC_PREVIEW,setSnapshotPreviewMode} from './snapshot-fixtures.js';
const {refreshNotams}=mountDashboard({NotamReader,NotamSnapshots,preview:SPATCHIN_SYNTHETIC_PREVIEW});
document.getElementById('preview-state').addEventListener('change',event=>{
 setSnapshotPreviewMode(event.target.value);
 refreshNotams();
});
