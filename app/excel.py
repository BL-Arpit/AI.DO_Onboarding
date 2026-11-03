import io
import re
import zipfile
from pathlib import Path
from openpyxl import Workbook,load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from .people import clean_person

# Deliberately explicit aliases: no guessing which personal data column is a name.
ALIASES={
    'name':('name','fullname','employeename','candidatename','nameofemployee'),
    'email':('email','emailid','emailaddress','mailid'),
    'phone':('phone','phonenumber','mobile','mobilenumber','contactnumber'),
    'client':('client','clientname','company','companyname'),
    'track':('track','resourcetrack'),
}
HEADERS={alias:key for key,aliases in ALIASES.items() for alias in aliases}

def cell_text(value):
    if value is None:return ''
    if isinstance(value,float) and value.is_integer():return str(int(value))
    return str(value).strip()

def parse_excel(content,filename,sheet_name=None):
    suffix=Path(filename).suffix.lower()
    if suffix not in ('.xlsx','.xls'):
        raise ValueError('Upload a raw .xlsx or .xls Excel file.')
    workbook=None
    try:
        if suffix=='.xlsx':
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if sum(f.file_size for f in archive.infolist())>50*1024*1024:
                    raise ValueError('Workbook expands beyond 50 MB.')
            workbook=load_workbook(io.BytesIO(content),read_only=True,data_only=False)
            names=workbook.sheetnames
            if sheet_name and sheet_name not in names:raise ValueError('Worksheet not found.')
            sheet=workbook[sheet_name] if sheet_name else workbook.worksheets[0]
            used_name=sheet.title
            rows=[]
            for row in sheet.iter_rows():
                if len(row)>100:raise ValueError('Use no more than 100 columns.')
                values=[cell_text(c.value) for c in row]
                formula=any(c.data_type=='f' for c in row)
                rows.append((values,formula))
                if len(rows)>1001:raise ValueError('Use no more than 1,000 employee rows.')
        else:
            import xlrd
            workbook=xlrd.open_workbook(file_contents=content,on_demand=True)
            names=workbook.sheet_names()
            if sheet_name and sheet_name not in names:raise ValueError('Worksheet not found.')
            sheet=workbook.sheet_by_name(sheet_name) if sheet_name else workbook.sheet_by_index(0)
            used_name=sheet.name
            if sheet.nrows>1001 or sheet.ncols>100:raise ValueError('Use at most 1,000 employee rows and 100 columns.')
            rows=[([cell_text(sheet.cell_value(r,c)) for c in range(sheet.ncols)],False) for r in range(sheet.nrows)]
        if not rows:raise ValueError('The worksheet is empty.')
        mapping={}
        for i,header in enumerate(rows[0][0]):
            key=HEADERS.get(re.sub(r'[^a-z0-9]','',header.lower()))
            if key:
                if key in mapping:raise ValueError('Duplicate header for '+key+'.')
                mapping[key]=i
        missing={'name','email','phone'}-set(mapping)
        if missing:raise ValueError('Missing columns: '+', '.join(sorted(missing)))
        accepted=[];rejected=[];seen=set()
        for number,(row,formula) in enumerate(rows[1:],start=2):
            if not any(row):continue
            data={key:row[index] if index<len(row) else '' for key,index in mapping.items()}
            person,issues=clean_person(data)
            if formula:issues.append('Replace formulas with raw values.')
            if person['email'] in seen:issues.append('Duplicate email within workbook.')
            if issues:rejected.append({'row':number,'name':person['name'],'issues':issues})
            else:
                seen.add(person['email']);accepted.append({'row':number,'person':person})
        return {'sheet':used_name,'sheets':names,'accepted':accepted,'rejected':rejected}
    except ValueError:raise
    except Exception as exc:
        raise ValueError('Could not read this Excel workbook. Check its format and remove password protection.') from exc
    finally:
        if workbook:
            if suffix=='.xlsx':workbook.close()
            else:workbook.release_resources()

def master_table(employees):
    """One row per saved employee across every conversation and import."""
    import json
    def flatten(value,prefix=''):
        result={}
        for key,item in sorted(value.items()):
            column=prefix+'.'+key if prefix else key
            if isinstance(item,dict):result.update(flatten(item,column))
            else:result[column]=json.dumps(item,ensure_ascii=False) if isinstance(item,list) else cell_text(item)
        return result
    people=list(employees)
    fields=[flatten(person.get('fields',{})) for person in people]
    extra=sorted({key for person in fields for key in person})
    columns=['employee_id','name','email','phone','client','track','status','verification_status']+extra
    rows=[]
    for person,details in zip(people,fields):
        rows.append([person['id']]+[cell_text(person.get(key,'')) for key in columns[1:7]]+
                    [cell_text(person.get('verification',{}).get('status',''))]+[details.get(key,'') for key in extra])
    return {'columns':columns,'rows':rows}

def export_excel(employees):
    workbook=Workbook();sheet=workbook.active;sheet.title='Master Employees'
    data=master_table(employees)
    sheet.append([ILLEGAL_CHARACTERS_RE.sub('',cell_text(v)) for v in data['columns']])
    for row in data['rows']:sheet.append([ILLEGAL_CHARACTERS_RE.sub('',cell_text(v)) for v in row])
    # Force strings to literal cells, including values beginning with =, +, -, @.
    for row in sheet:
        for cell in row:
            cell.data_type='s';cell.number_format='@'
    sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions
    from openpyxl.utils import get_column_letter
    for index,column in enumerate(data['columns'],1):
        sheet.column_dimensions[get_column_letter(index)].width=36 if column=='email' else 26
    output=io.BytesIO();workbook.save(output);workbook.close();return output.getvalue()
