"""Measure real rendered contrast on every dark surface."""
import asyncio
from playwright.async_api import async_playwright

def lum(c):
    def f(v):
        v/=255
        return v/12.92 if v<=0.03928 else ((v+0.055)/1.055)**2.4
    r,g,b=c
    return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b)

def ratio(fg,bg):
    a,b=lum(fg),lum(bg)
    hi,lo=max(a,b),min(a,b)
    return round((hi+0.05)/(lo+0.05),2)

def parse(s):
    import re
    m=re.findall(r'[\d.]+',s)
    return tuple(int(float(x)) for x in m[:3])

async def m():
    async with async_playwright() as b_:
        b=await b_.chromium.launch(); ctx=await b.new_context(viewport={'width':1440,'height':900})
        pg=await ctx.new_page()
        bad=[]
        for page in ('media.html','podcasts.html','index.html','about.html','studio.html'):
            await pg.goto('http://127.0.0.1:8899/'+page,wait_until='load')
            await pg.wait_for_timeout(600)
            rows=await pg.evaluate("""()=>{
              var out=[];
              document.querySelectorAll('.k-card--premium p,.k-card--premium li,'
                +'.sec--dark p,.sec--band p,.sec--image p,.sec--ink p,'
                +'.k-card--premium h3,.sec--dark h2,.sec--band h3').forEach(function(e){
                if(!e.offsetParent) return;
                var cs=getComputedStyle(e), bg=e, c='';
                while(bg&&bg!==document.documentElement){
                  var b=getComputedStyle(bg).backgroundColor;
                  if(b&&b!=='rgba(0, 0, 0, 0)'){c=b;break;}
                  bg=bg.parentElement;}
                out.push({sel:e.tagName.toLowerCase()+'.'+(e.className||'').split(' ')[0],
                          fg:cs.color, bg:c, txt:(e.textContent||'').trim().slice(0,28)});});
              return out;}""")
            for r in rows:
                if not r['bg']: continue
                cr=ratio(parse(r['fg']),parse(r['bg']))
                if cr < 4.5:
                    bad.append((page,r['sel'],cr,r['txt']))
        print('Contrast below 4.5:1 —', len(bad))
        for p,s,c,t in bad[:14]:
            print(f'  {c:>5}:1  {p:<16} {s:<26} "{t}"')
        await b.close()
asyncio.run(m())
