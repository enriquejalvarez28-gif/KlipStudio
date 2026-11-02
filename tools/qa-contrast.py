"""Measure real rendered contrast on every dark surface.

This used to sample a hand-written list of selectors — p, li, h2, h3 on
dark sections and charcoal cards. It passed while the checked items in the
Production and Content cards, the card numbers and the FROM labels were
rendering #d5d3cf on cream: their text sits in a <span>, and no span was
in the list. A blanket `.sec--band span` rule was beating the per-card
override, and the check had no way to see it.

So it no longer takes a list. It walks every element that holds text of
its own, on every built page, and measures what is actually painted. A
selector list can only find the faults someone already thought of.

It reports suspects, not verdicts. Backgrounds painted by ::before (the
red fill on a ghost button) and captions laid over an <img> are invisible
to it, so white text that is in fact over red or over a photograph is
flagged as white on light. Confirm each before changing anything.

Known and accepted at launch, 2026-11-02 — 28 rows: the struck-through
regular price (4.45:1, deliberately muted), the red 04 on the charcoal
package card, the brand red on white in ghost buttons and their arrows,
article bylines and dates, and the overlay labels on video thumbnails.
Anything beyond those is new.
"""
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

def flatten(layers):
    """Composite the background layers under a piece of text.

    `layers` is ordered nearest-to-text first and ends at the first opaque
    colour. Blending them is what tells a white glyph on a 12%-white
    button over charcoal (legible) from white on white (not).
    Returns None when nothing opaque was found.
    """
    import re
    if not layers:
        return None
    vals = []
    for s in layers:
        n = re.findall(r'[\d.]+', s)
        if len(n) < 3:
            return None
        a = float(n[3]) if len(n) > 3 else 1.0
        vals.append(([float(n[0]), float(n[1]), float(n[2])], a))
    if vals[-1][1] < 0.999:
        return None                      # never reached an opaque backdrop
    out = vals[-1][0]
    for col, a in reversed(vals[:-1]):   # bottom-up, each painted over
        out = [col[i] * a + out[i] * (1 - a) for i in range(3)]
    return tuple(int(round(v)) for v in out)


def parse(s):
    import re
    m=re.findall(r'[\d.]+',s)
    return tuple(int(float(x)) for x in m[:3])

async def m(port):
    async with async_playwright() as b_:
        b=await b_.chromium.launch(); ctx=await b.new_context(viewport={'width':1440,'height':900})
        pg=await ctx.new_page()
        bad=[]
        import glob, os
        pages=sorted(os.path.basename(p) for p in
                     glob.glob(os.path.join(os.path.dirname(os.path.dirname(
                         os.path.abspath(__file__))),'*.html')))
        for page in pages:
            await pg.goto(f'http://127.0.0.1:{port}/'+page,wait_until='load')
            await pg.wait_for_timeout(600)
            # the popup is dismissed by its own button, never removed: its
            # scroll handler runs against the node
            try:
                await pg.click('#sp-close',timeout=1500)
            except Exception:
                pass
            await pg.evaluate('()=>window.scrollTo(0,document.body.scrollHeight)')
            await pg.wait_for_timeout(600)
            rows=await pg.evaluate(r"""()=>{
              var out=[];
              document.querySelectorAll('body *').forEach(function(e){
                if(!e.offsetParent) return;
                // only elements holding text of their own, so a wrapper is
                // not measured against its child's colour
                var own='';
                for(var n=e.firstChild;n;n=n.nextSibling)
                  if(n.nodeType===3) own+=n.nodeValue;
                own=own.trim();
                if(!own) return;
                var cs=getComputedStyle(e);
                if(cs.visibility==='hidden'||parseFloat(cs.opacity)<0.1) return;
                if(parseFloat(cs.fontSize)<9) return;
                // a glyph painted in its own background colour is a
                // shape, not text — the red separator dots are a "." the
                // page is not meant to show
                if(cs.backgroundColor===cs.color) return;
                // every background between the text and the first opaque
                // one, so a translucent layer is composited rather than
                // treated as solid: the popup's close button is white on
                // 12% white over charcoal, which is legible, and a
                // translucent header is not the colour behind it either
                var layers=[], bg=e;
                while(bg&&bg!==document.documentElement){
                  var st=getComputedStyle(bg), b=st.backgroundColor;
                  if(b&&b!=='rgba(0, 0, 0, 0)'){
                    layers.push(b);
                    var al=b.match(/rgba\([^)]*,\s*([\d.]+)\s*\)/);
                    if(!al||parseFloat(al[1])>=0.999) break;
                  }
                  // text over an image gets no reliable background,
                  // whether the image is a CSS background or an <img>
                  // the caption is positioned over
                  if(st.backgroundImage!=='none') return;
                  if((st.position==='absolute'||st.position==='fixed')
                     && bg.parentElement
                     && bg.parentElement.querySelector('img,video,picture'))
                    return;
                  bg=bg.parentElement;}
                out.push({sel:e.tagName.toLowerCase()+'.'+(e.className||'')
                            .toString().split(' ')[0],
                          fg:cs.color, layers:layers, txt:own.slice(0,28)});});
              return out;}""")
            seen=set()
            for r in rows:
                bgc=flatten(r['layers'])
                if not bgc: continue
                r['bg']=str(bgc)
                cr=ratio(parse(r['fg']),bgc)
                if cr >= 4.5: continue
                k=(page,r['sel'],r['fg'],r['bg'])
                if k in seen: continue
                seen.add(k)
                bad.append((page,r['sel'],cr,r['txt']))
        print('Contrast below 4.5:1 —', len(bad))
        for p,s,c,t in bad[:40]:
            print(f'  {c:>5}:1  {p:<16} {s:<26} "{t}"')
        await b.close()
        return 1 if bad else 0


def main():
    import functools, http.server, socketserver, threading, os, sys
    root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    h=functools.partial(http.server.SimpleHTTPRequestHandler,directory=root)
    socketserver.TCPServer.allow_reuse_address=True
    # port 0 lets the OS pick, so the check never collides with a dev
    # server someone already has running
    httpd=socketserver.TCPServer(('127.0.0.1',0),h)
    threading.Thread(target=httpd.serve_forever,daemon=True).start()
    try:
        return asyncio.run(m(httpd.server_address[1]))
    finally:
        httpd.shutdown()


if __name__=='__main__':
    import sys
    sys.exit(main())
