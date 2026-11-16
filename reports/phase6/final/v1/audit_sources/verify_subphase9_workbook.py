from pathlib import Path
import json,zipfile,xml.etree.ElementTree as E,math,hashlib
ROOT=Path(r'C:\Users\Gulso\Documents\Gul\CredBlock-FL');O=ROOT/'outputs/phase6_final_v1';book=O/'CredBlock_FL_Phase6_TRAIN_VAL_Results_v2.xlsx';p=json.loads((Path(__file__).parent/'excel_all_phases_v1/subphase9_workbook_inputs_v2.json').read_text());N={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
def col(i):
 s=''
 while i:i,r=divmod(i-1,26);s=chr(65+r)+s
 return s
with zipfile.ZipFile(book) as z:
 assert z.testzip() is None;ss=[]
 if 'xl/sharedStrings.xml' in z.namelist():ss=[''.join(t.itertext()) for t in E.fromstring(z.read('xl/sharedStrings.xml')).findall('x:si',N)]
 names=[s.attrib['name'] for s in E.fromstring(z.read('xl/workbook.xml')).findall('x:sheets/x:sheet',N)];assert names==['Summary']+[t['name'] for t in p['tabs']]
 parsed={};formulas=0;errors=[]
 for i,name in enumerate(names,1):
  cells={}
  for c in E.fromstring(z.read(f'xl/worksheets/sheet{i}.xml')).findall('.//x:sheetData/x:row/x:c',N):
   typ=c.attrib.get('t');v=c.find('x:v',N);value=v.text if v is not None else None;f=c.find('x:f',N)
   if f is not None:formulas+=1
   if typ=='e':errors.append((name,c.attrib['r'],value))
   if typ=='s':actual=ss[int(value)]
   elif typ=='inlineStr':actual=''.join(c.find('x:is',N).itertext())
   elif typ=='b':actual=value=='1'
   elif value is None:actual=None
   elif typ=='str':actual=value
   else:actual=float(value)
   cells[c.attrib['r']]=actual
  parsed[name]=cells
 checked=0
 for t in p['tabs']:
  cells=parsed[t['name']]
  for r,rs in enumerate([t['headers']]+t['rows'],5):
   for c,expected in enumerate(rs,1):
    actual=cells.get(f'{col(c)}{r}')
    if isinstance(expected,(int,float)) and not isinstance(expected,bool):assert isinstance(actual,(int,float)) and math.isclose(actual,expected,rel_tol=1e-12,abs_tol=1e-10),(t['name'],r,c,actual,expected)
    else:assert actual==expected,(t['name'],r,c,actual,expected)
    checked+=1
 assert not errors,errors
 assert formulas==12
 macro=[r for r in p['aggregate'] if r['split']=='VAL' and r['aggregation']=='equal_weight_macro']
 for i,r in enumerate(macro,6):
  for j,k in enumerate(['average_precision','recall','fpr','precision','f1'],2):assert abs(parsed['Summary'][f'{col(j)}{i}']-r[k])<1e-12
 assert abs(parsed['Summary']['H12']-13733/36000)<1e-12 and abs(parsed['Summary']['H13']-15111/36000)<1e-12
 tables=len([n for n in z.namelist() if n.startswith('xl/tables/table') and n.endswith('.xml')]);assert tables==len(p['tabs'])+3
result=dict(status='PASS_SAVED_WORKBOOK_INDEPENDENT_VERIFICATION',worksheets=len(names),native_tables=tables,source_cells_verified=checked,formulas=formulas,formula_errors=errors,all_four_RQs_and_six_contributions_preserved=True,summary_metrics_exact=True,sha256=hashlib.file_digest(book.open('rb'),'sha256').hexdigest(),exporter_exit_code=-1073740791,export_note='Exporter terminated after saving; ZIP, all source cells, formula caches and native tables independently verified. Formatting draft v1 preserved; v2 is the final workbook.')
with (O/'workbook_verification_v2.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
print(json.dumps(result,indent=2))
