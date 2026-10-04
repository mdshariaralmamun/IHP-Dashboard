
import os, sys
root = r'E:\ENGINEERING_DATA'
office_ext = {'.doc','.docx','.dot','.dotx','.xls','.xlsx','.xlsm','.xlt','.xltx','.ppt','.pptx','.pdf','.txt','.md','.csv','.rtf','.odt','.ods'}
# top-level dirs
tops = sorted([d for d in os.listdir(root) if os.path.isdir(os.path.join(root,d))])
print("TOP-LEVEL DIRS:", tops)
for top in tops:
    tdir = os.path.join(root, top)
    files = []
    nimg = 0
    for dp, dns, fns in os.walk(tdir):
        for f in fns:
            ext = os.path.splitext(f)[1].lower()
            full = os.path.join(dp, f)
            if ext in office_ext:
                files.append(os.path.relpath(full, root))
            elif ext in ('.jpg','.jpeg','.png','.gif','.bmp','.tif','.tiff','.db'):
                nimg += 1
    print("="*80)
    print(f"## {top}: {len(files)} office/template files, {nimg} images/other")
    for f in sorted(files):
        print("   ", f)
