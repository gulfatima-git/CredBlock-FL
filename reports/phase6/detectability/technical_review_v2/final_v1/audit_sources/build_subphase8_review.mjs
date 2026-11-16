import fs from 'node:fs/promises';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const here='C:/Users/Gulso/OneDrive/Documents/ChatGPT/research/excel_all_phases_v1';
const root='C:/Users/Gulso/Documents/Gul/CredBlock-FL';
const out=`${root}/outputs/phase6_subphase8_technical_review_20261116_v1`;
await fs.mkdir(out,{recursive:true});
try{await fs.access(`${out}/CredBlock_FL_Phase6_Subphase8_Technical_Review_v1.xlsx`);throw new Error('Refuse existing workbook overwrite');}catch(e){if(e.code!=='ENOENT')throw e;}
const input=JSON.parse(await fs.readFile(`${here}/subphase8_review_inputs.json`,'utf8')),result=input.summary;
if(result.status!=='PASS'||result.user_accepted!==false)throw new Error('Technical PASS pending acceptance required');
const wb=Workbook.create();
const summary=wb.worksheets.add('Summary');
const letters=i=>{let s='';for(i++;i>0;i=Math.floor((i-1)/26))s=String.fromCharCode(65+(i-1)%26)+s;return s;};
const style=(s,range,header)=>{
 s.getRange(range).format.font={name:'Arial',size:10,color:'#243347'};
 s.getRange(range).format.rowHeight=22;
 s.getRange(header).format.fill='#233B57';s.getRange(header).format.font={name:'Arial',size:10,bold:true,color:'#FFFFFF'};
 s.getRange(header).format.wrapText=true;s.getRange(header).format.rowHeight=48;
};
function title(s,text,context){s.showGridLines=false;s.getRange('A2').values=[[text]];s.getRange('A2').format.font={name:'Arial',size:15,bold:true,color:'#233B57'};s.getRange('A3').values=[[context]];s.getRange('A3').format.font={name:'Arial',size:10,color:'#526170'};s.freezePanes.freezeRows(5);}
for(const tab of input.tabs){
 const s=wb.worksheets.add(tab.name);title(s,`Subphase 8 — ${tab.name}`,`Source: ${tab.source}`);
 const last=letters(tab.headers.length-1),end=5+tab.rows.length;
 s.getRange(`A5:${last}${end}`).values=[tab.headers,...tab.rows];
 s.tables.add(`A5:${last}${end}`,true,`Review${tab.name}`);style(s,`A5:${last}${end}`,`A5:${last}5`);
 for(let i=0;i<tab.headers.length;i++)s.getRange(`${letters(i)}5:${letters(i)}${end}`).format.columnWidth=(i===0?48:24);
 if(tab.name==='Sidecars'){s.getRange(`A5:B${end}`).format.columnWidth=90;s.getRange(`A6:B${end}`).format.wrapText=true;s.getRange(`A6:F${end}`).format.rowHeight=60;s.getRange(`E5:E${end}`).format.columnWidth=68;s.getRange(`F5:F${end}`).format.columnWidth=65;}
 if(tab.name==='Campaigns'){s.getRange(`Q6:Q${end}`).setNumberFormat('0.000000');s.getRange(`S6:S${end}`).setNumberFormat('0.000000');}
 if(tab.name==='Organizations')s.getRange(`P6:Q${end}`).setNumberFormat('0.000000');
}
title(summary,'Phase 6 Subphase 8 — Independent technical acceptance','16 November 2026 | Technical PASS; user acceptance pending. Subphase 9 not started.');
for(const [col,width]of [['A',28],['B',19],['C',19],['D',20],['E',22],['F',22],['G',24],['H',23]])summary.getRange(`${col}5:${col}48`).format.columnWidth=width;
const a=result.aggregates;
const top=[['Policy','Campaigns','Detected','Undetected','Undetected fraction','Target User occurrences','Detected User occurrences','Detected User fraction'],...a.map(r=>[r.detector_family,r.campaigns,r.detected_campaigns,r.undetected_campaigns,null,r.exposed_user_occurrences,r.detected_user_occurrences,null])];
summary.getRange('A5:H7').values=top;summary.tables.add('A5:H7',true,'ReviewHeadline');style(summary,'A5:H7','A5:H5');
summary.getRange('E6:E7').formulas=[['=D6/B6'],['=D7/B7']];summary.getRange('H6:H7').formulas=[['=G6/F6'],['=G7/F7']];summary.getRange('E6:E7').setNumberFormat('0.00%');summary.getRange('H6:H7').setNumberFormat('0.00%');
const org=[['Organization','Policy','Targeted trials','Detected trials','Exposed User occurrences','Detected User occurrences','Detected User fraction','Qualifying alert rows'],...result.per_organization.map(r=>[r.organization,r.detector_family,r.targeted_org_campaign_trials,r.detected_org_campaign_trials,r.exposed_local_user_occurrences,r.detected_local_user_occurrences,null,r.qualifying_alert_rows])];
summary.getRange('A11:H21').values=org;summary.tables.add('A11:H21',true,'ReviewOrganizationSummary');style(summary,'A11:H21','A11:H11');
summary.getRange('B12:B21').format.columnWidth=26;
for(let r=12;r<=21;r++)summary.getRange(`G${r}`).formulas=[[`=F${r}/E${r}`]];summary.getRange('G12:G21').setNumberFormat('0.00%');
const notes=[
 '0/171 wholly undetected campaigns under both policies. This VAL inventory contains no all-targeted-organizations local-undetected subset.',
 'User counts are branch-local exposed target occurrences, not globally unique people. Organization failures and incomplete User coverage remain visible.',
 'The 1% empirical FPR belongs to eligible fixed-grid VAL User-time negatives; these event/campaign measurements are separate.',
 'Frozen observations, model scores, thresholds and decisions were reused. No GNN inference, training, calibration or TEST outcome queries.',
 '855 databases passed immutable inspection; 855 empty WALs and 855 SHM files were inventoried and byte-preserved. No checkpoints or repairs.',
 'Frozen campaign method and all prior accepted evidence remain unchanged. Earlier failed checker attempts are preserved.',
 'Factors stay stratified by design family. Shared background and three temporal blocks prevent IID uncertainty claims.',
 'Full report: reports/phase6/detectability/technical_review_v2/final_v1/TECHNICAL_ACCEPTANCE_REPORT.md',
 'Sources: same folder summary.json; continuation_00004 CSVs and sidecar inventory. Timestamps are naive source time strings.',
 'Prior all-phases master workbooks are preserved. This workbook is the complete Subphase 8 technical-review supplement.'
];notes.forEach((v,i)=>{summary.getRange(`A${25+i}`).values=[[v]];summary.getRange(`A${25+i}`).format.font={name:'Arial',size:10,color:'#526170'};});
const check=[['Audit evidence','Verified count'],['VAL campaigns',171],['Organization replays',855],['Completion manifests',result.checks.completion_manifests],['Manifest hash entries',result.checks.artifact_hash_entries],['Prior files preserved',result.prior_files_preserved],['Boundary tests passed',35]];
summary.getRange('A38:B44').values=check;style(summary,'A38:B44','A38:B38');
wb.recalculate();
if(summary.getRange('E6').values[0][0]!==0||summary.getRange('E7').values[0][0]!==0)throw new Error('Boundary fraction mismatch');
summary.getRange('D6').values=[[1]];wb.recalculate();if(Math.abs(summary.getRange('E6').values[0][0]-1/171)>1e-12)throw new Error('Formula recalculation failed');summary.getRange('D6').values=[[0]];wb.recalculate();
const scan=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!',options:{useRegex:true,maxResults:15},summary:'Technical review workbook formula errors'});await fs.writeFile(`${out}/formula_scan.ndjson`,scan.ndjson);
for(const [range,name]of [['A2:H8','summary'],['A10:H22','organizations']])await fs.writeFile(`${out}/${name}.png`,new Uint8Array(await(await wb.render({sheetName:'Summary',range,scale:1.1})).arrayBuffer()));
await(await SpreadsheetFile.exportXlsx(wb)).save(`${out}/CredBlock_FL_Phase6_Subphase8_Technical_Review_v1.xlsx`);
await fs.writeFile(`${out}/build_evidence.json`,JSON.stringify({status:'EXPORTED',worksheets:6,formulas:14,expected_source_rows:input.tabs.map(t=>({sheet:t.name,rows:t.rows.length,columns:t.headers.length})),formula_recalculation:'PASS'},null,2));
