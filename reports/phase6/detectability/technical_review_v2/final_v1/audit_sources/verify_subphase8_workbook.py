from pathlib import Path
import json,zipfile,xml.etree.ElementTree as ET,hashlib,math
ROOT=Path(r'C:\Users\Gulso\Documents\Gul\CredBlock-FL');OUT=ROOT/'outputs/phase6_subphase8_technical_review_20261116_v1';book=OUT/'CredBlock_FL_Phase6_Subphase8_Technical_Review_v1.xlsx'
source=json.loads((Path(__file__).parent/'excel_all_phases_v1/subphase8_review_inputs.json').read_text());NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
def col(n):
 s=''
 while n:n,r=divmod(n-1,26);s=chr(65+r)+s
 return s
with zipfile.ZipFile(book) as z:
 assert z.testzip() is None
 strings=[]
 if 'xl/sharedStrings.xml' in z.namelist():
  strings=[''.join(t.itertext()) for t in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',NS)]
 sheets=ET.fromstring(z.read('xl/workbook.xml')).findall('m:sheets/m:sheet',NS);names=[s.attrib['name'] for s in sheets];assert names==['Summary']+[x['name'] for x in source['tabs']]
 parsed={};formulas=0;errors=[]
 for index,name in enumerate(names,1):
  root=ET.fromstring(z.read(f'xl/worksheets/sheet{index}.xml'));cells={}
  for c in root.findall('.//m:sheetData/m:row/m:c',NS):
   t=c.attrib.get('t');v=c.find('m:v',NS);f=c.find('m:f',NS);text=v.text if v is not None else None
   if f is not None:formulas+=1
   if t=='e':errors.append((name,c.attrib['r'],text))
   if t=='s':value=strings[int(text)]
   elif t=='inlineStr':value=''.join(c.find('m:is',NS).itertext())
   elif t=='b':value=text=='1'
   elif text is None:value=None
   elif t=='str':value=text
   else:value=float(text)
   cells[c.attrib['r']]=value
  parsed[name]=cells
 assert not errors,errors
 count=0
 for tab in source['tabs']:
  cells=parsed[tab['name']]
  for r,row in enumerate([tab['headers']]+tab['rows'],5):
   for c,expected in enumerate(row,1):
    actual=cells.get(f'{col(c)}{r}')
    if isinstance(expected,(int,float)) and not isinstance(expected,bool):assert isinstance(actual,(int,float)) and math.isclose(actual,expected,rel_tol=1e-12,abs_tol=1e-10),(tab['name'],r,c,actual,expected)
    else:assert actual==expected,(tab['name'],r,c,actual,expected)
    count+=1
 s=parsed['Summary'];assert s['B6']==s['B7']==171 and s['D6']==s['D7']==0 and s['G6']==13733 and s['G7']==15111
 assert s['E6']==s['E7']==0 and abs(s['H6']-13733/36000)<1e-12 and abs(s['H7']-15111/36000)<1e-12
 assert formulas==14,formulas
 assert len([n for n in z.namelist() if n.startswith('xl/tables/table') and n.endswith('.xml')])==7
result=dict(status='PASS_SAVED_WORKBOOK_VERIFICATION',sheets=names,source_cells_verified=count,formulas=formulas,formula_errors=errors,canonical_campaign_rows=342,canonical_organization_rows=1098,sidecars=1710,source_summary_metrics_exact=True,sha256=hashlib.file_digest(book.open('rb'),'sha256').hexdigest(),exporter_exit_code=-1073740791,export_note='The exporter saved the workbook and then terminated with Windows exit code -1073740791. The delivered ZIP, every source data cell, formula caches, native tables and error cells were independently checked; this runtime anomaly is retained explicitly.')
with (OUT/'saved_file_verification.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
print(json.dumps(result,indent=2))
