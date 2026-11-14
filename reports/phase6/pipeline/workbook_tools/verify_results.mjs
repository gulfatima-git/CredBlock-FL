import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url);
const entry=require.resolve('@oai/artifact-tool',{paths:['C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1111-570-0_26.1111.570.0_x64__3k8sg7r9htsxt/dependencies/node/node_modules']});
const {FileBlob,SpreadsheetFile}=await import(pathToFileURL(entry).href);
const root='C:/Users/Gulso/Documents/Gul/CredBlock-FL';
const file=`${root}/outputs/phase6_subphase2_v1/CredBlock_FL_Phase6_Input_Pipeline_v1.xlsx`;
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(file));
const sheet=wb.worksheets.getItem('Phase 6 Input Pipeline');
const initial=sheet.getRange('E7').values[0][0];
const source=sheet.getRange('I23').values[0][0];
sheet.getRange('I23').values=[[source+1]];
wb.recalculate();
const changed=sheet.getRange('E7').values[0][0];
if(Math.abs(changed-initial-1000/6)>1e-8)throw new Error('Dependent formula failed to recalculate');
sheet.getRange('I23').values=[[source]];
wb.recalculate();
if(Math.abs(sheet.getRange('E7').values[0][0]-initial)>1e-8)throw new Error('Formula not restored');
const evidence={status:'PASS',engine:'Bundled Artifact Tool',saved_file_reopened:true,
  temporary_one_second_input_change_updates_mean_ms:1000/6,restored:true,
  original_xlsx_not_modified:true,native_excel_engine_tested:false};
await fs.writeFile(`${root}/reports/phase6/pipeline/workbook_recalculation_v1.json`,JSON.stringify(evidence,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify(evidence));
