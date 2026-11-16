import fs from 'node:fs/promises';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root='C:/Users/Gulso/Documents/Gul/CredBlock-FL',here='C:/Users/Gulso/OneDrive/Documents/ChatGPT/research/excel_all_phases_v1',out=`${root}/outputs/phase6_final_v1`;
const p=JSON.parse(await fs.readFile(`${here}/subphase9_workbook_inputs_v2.json`,'utf8'));
if(p.scope!=='OPTION_A_TRAIN_VAL_ONLY'||p.test_access||p.phase6_complete)throw new Error('Scope mismatch');
const target=`${out}/CredBlock_FL_Phase6_TRAIN_VAL_Results_v2.xlsx`;
try{await fs.access(target);throw new Error('No overwrite');}catch(e){if(e.code!=='ENOENT')throw e;}
const w=Workbook.create(),summary=w.worksheets.add('Summary');
const col=n=>{let s='';for(n++;n>0;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
function style(s,r,h){s.getRange(r).format.font={name:'Arial',size:10,color:'#233347'};s.getRange(r).format.rowHeight=22;s.getRange(h).format.fill='#233B57';s.getRange(h).format.font={name:'Arial',size:10,bold:true,color:'#FFFFFF'};s.getRange(h).format.wrapText=true;s.getRange(h).format.rowHeight=52;}
function title(s,t,scope){s.showGridLines=false;s.getRange('A2').values=[[t]];s.getRange('A2').format.font={name:'Arial',size:15,bold:true,color:'#233B57'};s.getRange('A3').values=[[scope]];s.getRange('A3').format.font={name:'Arial',size:10,color:'#526170'};s.freezePanes.freezeRows(5);}
let index=0;
for(const t of p.tabs){
 const s=w.worksheets.add(t.name),last=col(t.headers.length-1),end=t.rows.length+5;title(s,t.name,`Source: ${t.source}`);s.getRange(`A5:${last}${end}`).values=[t.headers,...t.rows];s.tables.add(`A5:${last}${end}`,true,`P6ReportingData${++index}`);style(s,`A5:${last}${end}`,`A5:${last}5`);
 for(let j=0;j<t.headers.length;j++)s.getRange(`${col(j)}5:${col(j)}${end}`).format.columnWidth=j===0?38:25;
 for(let j=0;j<t.headers.length;j++){
  const h=t.headers[j];if(['recall','precision','fpr','f1','specificity','accuracy','positive_fraction','average_precision','roc_auc'].includes(h))s.getRange(`${col(j)}6:${col(j)}${end}`).setNumberFormat('0.0000');
 }
 if(t.name==='RQ and contributions'){
  for(let j=2;j<t.headers.length-1;j++)s.getRange(`${col(j)}5:${col(j)}${end}`).format.columnWidth=65;
  s.getRange(`C6:J${end}`).format.wrapText=true;s.getRange(`A6:K${end}`).format.rowHeight=110;s.getRange(`A6:K${end}`).format.verticalAlignment='top';s.getRange(`A5:A${end}`).format.columnWidth=10;s.getRange(`B5:B${end}`).format.columnWidth=26;s.getRange(`C5:C${end}`).format.columnWidth=80;s.getRange(`K5:K${end}`).format.columnWidth=42;
 }
 if(t.name==='Sources'){s.getRange(`A5:A${end}`).format.columnWidth=120;s.getRange(`A6:A${end}`).format.wrapText=true;s.getRange(`A6:B${end}`).format.rowHeight=52;s.getRange(`B5:B${end}`).format.columnWidth=70;}
}
title(summary,'Phase 6 TRAIN/VAL research results','Option A reporting only. TEST deferred and unauthorized. Full Phase 6 completion pending.');
for(const [i,width]of [27,24,25,25,25,25,25,26].entries())summary.getRange(`${col(i)}5:${col(i)}48`).format.columnWidth=width;
summary.getRange('A5:F7').values=[['Detector','VAL macro AP','VAL macro recall','VAL macro FPR','VAL macro precision','VAL macro F1'],['GraphSAGE',null,null,null,null,null],['MLP',null,null,null,null,null]];style(summary,'A5:F7','A5:F5');summary.tables.add('A5:F7',true,'P6ReportingMacro');
const grid=p.tabs.find(t=>t.name==='Fixed grid');
for(const [i,det]of ['graphsage','tabular_mlp'].entries())for(const [j,metric]of ['average_precision','recall','fpr','precision','f1'].entries()){
 const c=col(grid.headers.indexOf(metric));const refs=grid.rows.map((r,k)=>({r,k})).filter(x=>x.r[1]==='VAL'&&x.r[2]===det).map(x=>`'Fixed grid'!${c}${x.k+6}`);summary.getRange(`${col(j+1)}${i+6}`).formulas=[[`=IF(COUNT(${refs.join(',')})=5,AVERAGE(${refs.join(',')}),"undefined")`]];
}
summary.getRange('B6:F7').setNumberFormat('0.000000');
const a=p.operational.aggregates;summary.getRange('A11:H13').values=[['Operational policy','Campaigns','Detected anywhere','Detected at all orgs','Undetected everywhere','Target User occurrences','Detected User occurrences','Detected User fraction'],...a.map(r=>[r.detector_family,r.campaigns,r.detected_campaigns,r.all_orgs_detected,r.undetected_campaigns,r.exposed_user_occurrences,r.detected_user_occurrences,null])];style(summary,'A11:H13','A11:H11');summary.tables.add('A11:H13',true,'P6ReportingOperational');summary.getRange('H12:H13').formulas=[['=G12/F12'],['=G13/F13']];summary.getRange('H12:H13').setNumberFormat('0.00%');
summary.getRange('A17:D22').values=[['Research item','Current evidence','Missing evidence','Responsible later phase'],['RQ1','Local/indicator baselines only','Federated fixed-FPR advantage; TEST','7, 8, 11'],['RQ2','Non-private local reference','Formal user-level DP utility sweep','8, 11'],['RQ3','Non-IID local reference','Poisoning and honest exclusion','8, 11'],['RQ4','Local resource costs only','Integrated ledger round overhead','10, 11'],['C1–C6','See exact source and full matrix','Full framework claims remain partial','7–11']];style(summary,'A17:D22','A17:D17');summary.getRange('A18:D22').format.wrapText=true;summary.getRange('A18:D22').format.rowHeight=45;summary.tables.add('A17:D22',true,'P6ReportingAlignmentSummary');
const notes=[
'0/171 VAL campaigns are wholly undetected locally. Do not manufacture a subset or claim federated rescue on this empty subset.',
'Fixed-grid eligible User-time metrics and operational campaign/User coverage use different denominators. 1% VAL FPR is not an event-driven FPR.',
'TRAIN scores are in-sample diagnostics. Frozen thresholds were selected on later VAL; TRAIN operating metrics are retrospective.',
'AP is tied-score grouped average precision. ROC-AUC is descriptive. Repeated background and three temporal blocks preclude naive IID confidence intervals.',
'Updates would transfer learned patterns in later federation. No explicit cross-organization graph, IP-link reconstruction or shared identity index exists.',
'All four RQs and six projected contributions retain their user-supplied wording in the alignment sheet. Unsupported claims remain marked.',
'Raw logs and local IDs remain outside this workbook. Missing values are blank; single-organization Raccount remains N/A.',
'Previous results, protocols, models, thresholds and workbooks are preserved. No TEST outcomes, fitting, inference or completed campaign evaluation was used.',
'Full report and reproducibility evidence: reports/phase6/final/v1. Subphase 9 user acceptance is pending; Phase 7 has not started.'
];notes.forEach((v,i)=>{summary.getRange(`A${26+i}`).values=[[v]];summary.getRange(`A${26+i}`).format.font={name:'Arial',size:10,color:'#526170'};});
w.recalculate();const expected=p.aggregate.filter(r=>r.split==='VAL'&&r.aggregation==='equal_weight_macro');for(let i=0;i<2;i++)if(Math.abs(summary.getRange(`C${i+6}`).values[0][0]-expected[i].recall)>1e-12)throw new Error('Macro formula mismatch');
const old=summary.getRange('G12').values[0][0];summary.getRange('G12').values=[[old+1]];w.recalculate();if(Math.abs(summary.getRange('H12').values[0][0]-(old+1)/36000)>1e-12)throw new Error('Formula recalc');summary.getRange('G12').values=[[old]];w.recalculate();
await fs.writeFile(`${out}/workbook_formula_scan_v2.ndjson`,(await w.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!',options:{useRegex:true,maxResults:15}})).ndjson);
for(const [sheetName,range,file]of [['Summary','A2:H14','workbook_summary_v2.png'],['Summary','A17:D22','workbook_alignment_summary_v2.png'],['RQ and contributions','A5:D8','workbook_alignment_detail_v2.png']])await fs.writeFile(`${out}/${file}`,new Uint8Array(await(await w.render({sheetName,range,scale:1})).arrayBuffer()));
await(await SpreadsheetFile.exportXlsx(w)).save(target);
await fs.writeFile(`${out}/workbook_build_evidence_v2.json`,JSON.stringify({sheets:p.tabs.length+1,formulas:12,recalculation:'PASS',sources:p.tabs.map(t=>({sheet:t.name,rows:t.rows.length,columns:t.headers.length}))},null,2));
