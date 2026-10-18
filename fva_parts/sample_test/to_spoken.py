import json,re,html,sys
S=json.load(open(sys.argv[1],encoding='utf-8')); out=[]
for i,s in enumerate(S,1):
    t=re.sub(r'</?speak>','',s['text']); t=re.sub(r'<break time="(\d+)ms"/>',lambda m:' ‖ ' if int(m.group(1))<800 else ' ‖‖ ',t)
    out.append(f'--- chunk {i}\n'+html.unescape(t))
open(sys.argv[2],'w',encoding='utf-8').write('\n'.join(out))
