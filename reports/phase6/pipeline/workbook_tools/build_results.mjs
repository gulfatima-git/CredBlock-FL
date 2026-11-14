import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url);
const entry=require.resolve('@oai/artifact-tool',{paths:['C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1111-570-0_26.1111.570.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules']});
const {Workbook,SpreadsheetFile}=await import(pathToFileURL(entry).href);
const root='C:/Users/Gulso/Documents/Gul/CredBlock-FL';
const evidence=`${root}/reports/phase6/pipeline/v2`;
const rows=JSON.parse(await fs.readFile(`${evidence}/representative_checks.json`,'utf8'));
const scale=JSON.parse(await fs.readFile(`${evidence}/scale_smoke.json`,'utf8'));
const out=`${root}/outputs/phase6_subphase2_v1`;
await fs.mkdir(out,{recursive:true});
try {await fs.access(`${out}/CredBlock_FL_Phase6_Input_Pipeline_v1.xlsx`);await fs.copyFile(`${out}/CredBlock_FL_Phase6_Input_Pipeline_v1.xlsx`,`${out}/reviewed_export.draft-backup`,1);}
catch(e) {if(e.code!=='ENOENT')throw e;}
const workbook=Workbook.create();
const s=workbook.worksheets.add('Phase 6 Input Pipeline');
s.showGridLines=false;
s.getRange('A1:L66').format.font={name:'Arial',size:10,color:'#243529'};
s.getRange('A1:L66').format.rowHeight=21;
s.getRange('A1:A66').format.columnWidth=18;
s.getRange('B1:B66').format.columnWidth=25;
s.getRange('C1:L66').format.columnWidth=16;
s.getRange('A2:F2').merge();s.getRange('A2').values=[['CredBlock-FL | Phase 6 input pipeline']];
s.getRange('A2:F2').format.font={size:14,bold:true,color:'#243529'};
s.getRange('A3:F3').merge();s.getRange('A3').values=[['Technical validation passed; Subphase 2 user acceptance pending']];
s.getRange('A4:F4').merge();s.getRange('A4').values=[['TRAIN inputs only. No model training or predictions. Recorded 14 Nov 2026.']];
s.getRange('A6:F6').values=[['Organization','Grid checks','Mean nodes','Mean CSR (ms)','Mean batch (ms)','Batch tensor (KiB)']];
s.getRange('A6:F6').format.fill='#DCECCB';s.getRange('A6:F6').format.font.bold=true;
for(let i=0;i<5;i++){
  const r=7+i;
  s.getRange(`A${r}`).values=[[`Org${i+1}`]];
  s.getRange(`B${r}:F${r}`).formulas=[[
    `=COUNTIFS($A$23:$A$52,A${r})`,
    `=AVERAGEIFS($C$23:$C$52,$A$23:$A$52,A${r})`,
    `=AVERAGEIFS($H$23:$H$52,$A$23:$A$52,A${r})*1000`,
    `=AVERAGEIFS($I$23:$I$52,$A$23:$A$52,A${r})*1000`,
    `=AVERAGEIFS($J$23:$J$52,$A$23:$A$52,A${r})/1024`
  ]];
}
s.getRange('B7:C11').setNumberFormat('#,##0');s.getRange('D7:F11').setNumberFormat('0.00');
s.getRange('A13:B18').values=[
 ['Subphase 0','USER_ACCEPTED'],['Subphase 1','USER_ACCEPTED'],['Phase 6 tests passed',85],
 ['Synthetic scale nodes',scale.nodes],['Scale batch time (s)',scale.sample_256_seconds],
 ['Scale RSS (MiB)',scale.rss_bytes/1048576]
];
s.getRange('A13:A18').format.font.bold=true;
s.getRange('B16').setNumberFormat('#,##0');s.getRange('B17:B18').setNumberFormat('0.00');
s.getRange('C13:F14').merge();s.getRange('C13').values=[['Scale fixture: degree-two synthetic graph; not real traffic throughput.']];
s.getRange('C13:F14').format.wrapText=true;
s.getRange('C15:F15').merge();s.getRange('C15').values=[['Cold first batch includes PyG import; no model inference.']];
s.getRange('C16:F18').merge();s.getRange('C16').values=[['1% FPR, split assignments and scoring grid preserved. Final TEST evaluation requires the frozen protocol in version control.']];
s.getRange('C16:F18').format.wrapText=true;
s.getRange('A20:L20').merge();s.getRange('A20').values=[['Source: reports/phase6/pipeline/v2/representative_checks.json and scale_smoke.json (local measured inputs).']];
s.getRange('A21:L21').merge();s.getRange('A21').values=[['Real-data scope: TRAIN seed1001, one branch, six grids per organization. Example batches use observable recent activity; labels are separate.']];
s.getRange('A22:L22').values=[['Organization','Scoring time','Graph nodes','Directed edges','Demo Users','Eligible Users','Positive Users','CSR time (s)','Batch time (s)','Tensor bytes','Process RSS (B)','Retained events']];
s.getRange('A22:L22').format.fill='#DCECCB';s.getRange('A22:L22').format.font.bold=true;
const data=rows.map(r=>[r.organization,r.asof,r.nodes,r.directed_edges,r.demo_user_roots,r.eligible_demo_roots,r.positive_demo_roots,r.snapshot_and_csr_seconds,r.batch_and_supervision_seconds,r.model_batch_tensor_bytes,r.process_rss_bytes,r.retained_events]);
s.getRange('A23:L52').values=data;
s.getRange('C23:G52').setNumberFormat('#,##0');s.getRange('H23:I52').setNumberFormat('0.0000');s.getRange('J23:L52').setNumberFormat('#,##0');
s.getRange('A55:L55').merge();s.getRange('A55').values=[['Protocol SHA256: 9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b']];
s.getRange('A56:L56').merge();s.getRange('A56').values=[['Original Phase 5 research workbook and accepted Phase 5/6 evidence preserved; this is a new Phase 6 measurement record.']];
s.freezePanes.freezeRows(6);
workbook.recalculate();
const check=await workbook.inspect({kind:'table',range:'Phase 6 Input Pipeline!A6:F11',include:'values,formulas',tableMaxRows:6,tableMaxCols:6});
console.log(check.ndjson);
const errors=await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},summary:'New workbook formula error scan'});
console.log(errors.ndjson);
await fs.writeFile(`${out}/summary_preview.png`,new Uint8Array(await (await workbook.render({sheetName:s.name,range:'A1:F18',scale:1.5})).arrayBuffer()));
await fs.writeFile(`${out}/measurements_preview.png`,new Uint8Array(await (await workbook.render({sheetName:s.name,range:'A20:L28',scale:1.2})).arrayBuffer()));
await (await SpreadsheetFile.exportXlsx(workbook)).save(`${out}/CredBlock_FL_Phase6_Input_Pipeline_v1.xlsx`);
console.log('Workbook exported');
