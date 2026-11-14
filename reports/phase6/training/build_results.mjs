// One new workbook; accepted Phase 5/6 workbooks are never edited.
import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url);
const entry=require.resolve('@oai/artifact-tool',{paths:['C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1111-570-0_26.1111.570.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules']});
const {Workbook,SpreadsheetFile}=await import(pathToFileURL(entry).href);
const root='C:/Users/Gulso/Documents/Gul/CredBlock-FL';
const result=JSON.parse(await fs.readFile(`${root}/reports/phase6/training/final_v1/summary.json`,'utf8'));
if(result.organizations!==5||!result.status.startsWith('PASS_SUBPHASE3_FULL_FIVE'))throw new Error('Full five-model acceptance evidence required');
const out=`${root}/outputs/phase6_subphase3_v1`;
await fs.mkdir(out,{recursive:true});
const destination=`${out}/CredBlock_FL_Phase6_Local_Training_v1.xlsx`;
try {await fs.access(destination);await fs.copyFile(destination,`${destination}.draft-backup`,(await import('node:fs')).constants.COPYFILE_EXCL);}
catch(e){if(e.code!=='ENOENT')throw e;}
const wb=Workbook.create();
const s=wb.worksheets.add('Five local models');
s.showGridLines=false;
s.getRange('A1:J48').format.font={name:'Arial',size:10,color:'#243529'};
s.getRange('A1:J48').format.rowHeight=23;
s.getRange('A1:A48').format.columnWidth=14;
s.getRange('B1:B48').format.columnWidth=16;
s.getRange('C1:C48').format.columnWidth=10;
s.getRange('D1:E48').format.columnWidth=17;
s.getRange('F1:G48').format.columnWidth=14;
s.getRange('H1:I48').format.columnWidth=18;
s.getRange('J1:J48').format.columnWidth=14;
for(const row of [2,3,4,20,30,31,38,40,41,43,44])s.getRange(`A${row}:J${row}`).merge();
s.getRange('A2').values=[['CredBlock-FL | Five independent local GraphSAGE models']];
s.getRange('A2:J2').format.font={size:14,bold:true,color:'#243529'};
s.getRange('A3').values=[['Full TRAIN/VAL inventory verified; Subphase 3 user acceptance pending. TEST unopened.']];
s.getRange('A4').values=[['AP = average precision. Nominal 0.5 diagnostics are not calibrated 1% FPR results.']];
s.getRange('A6:J6').values=[['Organization','Width','Epoch','TRAIN eligible','VAL eligible','VAL AP','VAL BCE','Selected run (s)','Training RSS MiB','Exact repeat']];
s.getRange('A6:J6').format.fill='#DCECCB';s.getRange('A6:J6').format.font.bold=true;
s.getRange('A7:J11').values=result.models.map(r=>[r.organization,r.selected_candidate.hidden_dim,r.selected_epoch,
 r.selected_model_train_metrics.eligible,r.validation.eligible,r.validation.average_precision,r.validation.bce,
 r.selected_run_seconds,r.observed_training_rss_peak_bytes/1048576,r.exact_repeat_state_and_validation_scores?'Yes':'No']);
s.getRange('D7:E11').setNumberFormat('#,##0');s.getRange('F7:G11').setNumberFormat('0.000000');s.getRange('H7:I11').setNumberFormat('#,##0.000');
s.getRange('A14:B18').values=[['Macro VAL AP',null],['Subphase 2','USER_ACCEPTED'],['Total TRAIN units',null],['Total VAL units',null],['Grid caches verified',result.verified_cache_files]];
s.getRange('B14').formulas=[['=AVERAGE(F7:F11)']];
s.getRange('B16').formulas=[['=SUM(D7:D11)']];s.getRange('B17').formulas=[['=SUM(E7:E11)']];
s.getRange('B14').setNumberFormat('0.000000');s.getRange('B16:B18').setNumberFormat('#,##0');
s.getRange('C14:J16').merge();s.getRange('C14').values=[['Each model used 171 TRAIN + 171 VAL branches and all three campaign seeds. Counts are dependent benchmark User-times, not independent people.']];
s.getRange('C14:J16').format.wrapText=true;
s.getRange('C17:J18').merge();s.getRange('C17').values=[['Selected trial time includes training and validation. RSS is whole-process observed memory. Exact replay does not measure initialization uncertainty.']];
s.getRange('C17:J18').format.wrapText=true;
s.getRange('A20').values=[['Source: reports/phase6/training/final_v1/summary.json and verified local component artifacts.']];
s.getRange('A22:F22').values=[['Organization','New User N','New User AP','New-IP context N','New-IP AP','Local parameters']];
s.getRange('A22:F22').format.fill='#DCECCB';s.getRange('A22:F22').format.font.bold=true;
s.getRange('A22:F22').format.wrapText=true;s.getRange('A22:F22').format.rowHeight=40;
s.getRange('A23:F27').values=result.models.map(r=>[r.organization,r.validation.inductive_unseen_user.eligible,
 r.validation.inductive_unseen_user.average_precision??'N/A',r.validation.inductive_unseen_ip_context.eligible,
 r.validation.inductive_unseen_ip_context.average_precision??'N/A',r.model_parameters]);
s.getRange('B23:B27').setNumberFormat('#,##0');s.getRange('D23:D27').setNumberFormat('#,##0');
s.getRange('C23:C27').setNumberFormat('0.000000');s.getRange('E23:E27').setNumberFormat('0.000000');s.getRange('F23:F27').setNumberFormat('#,##0');
s.getRange('A30').values=[['Selected checkpoint files (project-relative; tensor weights and metadata)']];
s.getRange('A31').values=[['All five repeat runs reproduced checkpoint state digests and the complete VAL prediction CSV exactly.']];
for(let i=0;i<5;i++){
 const row=32+i;s.getRange(`A${row}`).values=[[result.models[i].organization]];
 s.getRange(`B${row}:J${row}`).merge();s.getRange(`B${row}`).values=[[result.models[i].checkpoint.replaceAll('\\','/').replace(`${root}/`,'')]];
}
s.getRange('A38').values=[['No thresholds, continuous alerts, indicator sharing, federation, differential privacy or blockchain implemented.']];
s.getRange('A40').values=[['Protocol SHA256: 9e44c7a8a66f553af79e4e3a834a2a01bb1300cb3fdfe5c993c5146c695a806b']];
s.getRange('A41').values=[['The frozen protocol must be in version control before final TEST evaluation.']];
s.getRange('A43').values=[['Next: user acceptance, then Subphase 4 non-graph comparator. All accepted earlier artifacts preserved.']];
s.freezePanes.freezeRows(6);
wb.recalculate();
// Verify a live formula dependency in memory, then restore the actual measurement.
const original=s.getRange('D7').values[0][0];const total=s.getRange('B16').values[0][0];
s.getRange('D7').values=[[original+1]];wb.recalculate();
if(s.getRange('B16').values[0][0]!==total+1)throw new Error('Total failed to recalculate');
s.getRange('D7').values=[[original]];wb.recalculate();
console.log((await wb.inspect({kind:'table',range:'Five local models!A6:J11',include:'values,formulas',tableMaxRows:6,tableMaxCols:10})).ndjson);
console.log((await wb.inspect({kind:'table',range:'Five local models!A14:B18',include:'values,formulas',tableMaxRows:5,tableMaxCols:2})).ndjson);
await fs.writeFile(`${out}/models_preview.png`,new Uint8Array(await (await wb.render({sheetName:s.name,range:'A1:J18',scale:1.25})).arrayBuffer()));
await fs.writeFile(`${out}/inductive_preview.png`,new Uint8Array(await (await wb.render({sheetName:s.name,range:'A20:J43',scale:1.1})).arrayBuffer()));
await (await SpreadsheetFile.exportXlsx(wb)).save(destination);
console.log('Workbook saved',destination);
