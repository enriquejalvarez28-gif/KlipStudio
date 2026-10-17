/* ============================================================
   KLIP — site behaviour, loaded by every page.

   The pages arrive complete: header, sections, footer and modal
   shells are all in the HTML that the build wrote, so a crawler
   (and a visitor on a slow phone) sees the finished page without
   running any of this.

   This file only makes it work: the drawer, booking and Calendly
   modals, the photographer list, the video lightbox, the Visibility
   Check, scroll reveals and motion. It renders no page content.

   Settings it needs (booking ids, Calendly links, photographers)
   are in the <script id="klip-config"> block the build inlines.
   ============================================================ */
(function(){
  var cfgEl=document.getElementById('klip-config');
  var D=cfgEl?JSON.parse(cfgEl.textContent):null; if(!D) return;
  var ar='<span class="ar" aria-hidden="true">&#8594;</span>';
  var REDUCE=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var IN_FRAME=(window.self!==window.top);


  var ICON={
    megaphone:'<path d="M3 10v4h3l5 4V6l-5 4H3z"/><path d="M16.5 8.5a5 5 0 0 1 0 7"/><path d="M19.5 6a8.5 8.5 0 0 1 0 12"/>',
    chart:'<path d="M4 20V11"/><path d="M10 20V5"/><path d="M16 20v-6"/><path d="M21 20H3"/>',
    search:'<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
    chip:'<rect x="7" y="7" width="10" height="10" rx="1.5"/><path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4"/>',
    doc:'<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M9 12h6M9 16h6"/>',
    growth:'<path d="M4 17l6-6 4 4 6-7"/><path d="M15 8h5v5"/>',
    gear:'<circle cx="12" cy="12" r="8"/><path d="M12 4v16M4.5 8l15 8M4.5 16l15-8"/>',
    sets:'<rect x="4" y="4" width="16" height="16" rx="1.5"/><path d="M4 14h6v6M14 4v6h6"/>',
    calendar:'<rect x="4" y="5" width="16" height="15" rx="1.5"/><path d="M4 10h16M9 3v4M15 3v4"/>',
    car:'<path d="M4 16v-3l2-5h12l2 5v3"/><path d="M4 16h16M7 16v2M17 16v2"/><circle cx="8" cy="13" r="1"/><circle cx="16" cy="13" r="1"/>',
    target:'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1"/>',
    globe:'<circle cx="12" cy="12" r="8"/><path d="M4 12h16M12 4c2.5 2.6 2.5 12.4 0 16M12 4c-2.5 2.6-2.5 12.4 0 16"/>',
    badge:'<path d="M12 3.2l2.2 2 3-.3.5 2.9 2.4 1.8-1.5 2.6 1.5 2.6-2.4 1.8-.5 2.9-3-.3-2.2 2-2.2-2-3 .3-.5-2.9L4 15.8l1.5-2.6L4 10.6l2.3-1.8.5-2.9 3 .3z"/>',
    window:'<rect x="3" y="5" width="18" height="14" rx="1.5"/><path d="M3 9.5h18"/><path d="M6 7.2h.01M8.4 7.2h.01"/>'
  };
  var SOCIAL={
    instagram:'<path d="M12 2.2c3.2 0 3.6 0 4.9.07 1.17.05 1.8.25 2.23.41.56.22.96.48 1.38.9.42.42.68.82.9 1.38.16.42.36 1.06.41 2.23.06 1.27.07 1.65.07 4.86s0 3.6-.07 4.86c-.05 1.17-.25 1.8-.41 2.23-.22.56-.48.96-.9 1.38-.42.42-.82.68-1.38.9-.42.16-1.06.36-2.23.41-1.27.06-1.65.07-4.86.07s-3.6 0-4.86-.07c-1.17-.05-1.8-.25-2.23-.41a3.8 3.8 0 0 1-1.38-.9 3.8 3.8 0 0 1-.9-1.38c-.16-.42-.36-1.06-.41-2.23C2.2 15.6 2.2 15.2 2.2 12s0-3.6.07-4.86c.05-1.17.25-1.8.41-2.23.22-.56.48-.96.9-1.38.42-.42.82-.68 1.38-.9.42-.16 1.06-.36 2.23-.41C8.4 2.2 8.8 2.2 12 2.2zm0 1.8c-3.14 0-3.5 0-4.74.07-.9.04-1.38.19-1.7.31-.43.17-.74.37-1.06.69-.32.32-.52.63-.69 1.06-.12.32-.27.8-.31 1.7C3.43 8.5 3.42 8.86 3.42 12s0 3.5.07 4.74c.4.9.19 1.38.31 1.7.17.43.37.74.69 1.06.32.32.63.52 1.06.69.32.12.8.27 1.7.31 1.24.06 1.6.07 4.74.07s3.5 0 4.74-.07c.9-.04 1.38-.19 1.7-.31.43-.17.74-.37 1.06-.69.32-.32.52-.63.69-1.06.12-.32.27-.8.31-1.7.06-1.24.07-1.6.07-4.74s0-3.5-.07-4.74c-.04-.9-.19-1.38-.31-1.7a2.85 2.85 0 0 0-.69-1.06 2.85 2.85 0 0 0-1.06-.69c-.32-.12-.8-.27-1.7-.31C15.5 4 15.14 4 12 4zm0 3.06a4.94 4.94 0 1 1 0 9.88 4.94 4.94 0 0 1 0-9.88zm0 1.8a3.14 3.14 0 1 0 0 6.28 3.14 3.14 0 0 0 0-6.28zm5.14-2.9a1.15 1.15 0 1 1 0 2.3 1.15 1.15 0 0 1 0-2.3z"/>',
    youtube:'<path d="M21.6 7.2a2.5 2.5 0 0 0-1.76-1.77C18.25 5 12 5 12 5s-6.25 0-7.84.43A2.5 2.5 0 0 0 2.4 7.2 26 26 0 0 0 2 12a26 26 0 0 0 .4 4.8 2.5 2.5 0 0 0 1.76 1.77C5.75 19 12 19 12 19s6.25 0 7.84-.43a2.5 2.5 0 0 0 1.76-1.77A26 26 0 0 0 22 12a26 26 0 0 0-.4-4.8zM10 15.2V8.8L15.5 12 10 15.2z"/>',
    tiktok:'<path d="M16.5 3h-2.9v12.2a2.4 2.4 0 1 1-2-2.37V9.8a5.5 5.5 0 1 0 5 5.47V9.42a6.4 6.4 0 0 0 3.8 1.25V7.73a3.6 3.6 0 0 1-3.9-3.6V3z"/>',
    linkedin:'<path d="M6.94 8.5H4V20h2.94V8.5zM5.47 4a1.7 1.7 0 1 0 0 3.4 1.7 1.7 0 0 0 0-3.4zM20 13.9c0-3.1-1.66-4.55-3.87-4.55-1.78 0-2.58.98-3.02 1.67V8.5H10.2V20h2.9v-6.3c0-1.66.31-3.27 2.37-3.27 2.03 0 2.06 1.9 2.06 3.38V20H20v-6.1z"/>'
  };
  function icon(n){ return '<svg viewBox="0 0 24 24" aria-hidden="true">'+(ICON[n]||'')+'</svg>'; }

  /* WebP with a JPEG fallback. Same markup, same box, smaller download. */
  /* A <picture> whose <source> 404s shows a broken image — the browser
     does not fall back to the <img>. So the smaller WebP is only offered
     for images we know have one (data/webp.json). An image uploaded
     through /admin simply serves as itself until someone runs
     tools/make-webp.js, and never breaks in the meantime. */
  function pic(src, alt, attrs){
    attrs=attrs||'';
    var tag='<img src="'+esc(src)+'" alt="'+esc(alt||'')+'" '+attrs+'>';
    if(!/\.jpe?g$/i.test(src)) return tag;
    var webp=src.replace(/\.jpe?g$/i,'.webp');
    var have=D.webp;
    if(have && have.indexOf(webp.split('/').pop())===-1) return tag;
    return '<picture><source srcset="'+esc(webp)+'" type="image/webp">'+tag+'</picture>';
  }
  function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
  function ext(h){ return /^https?:/i.test(h)?' target="_blank" rel="noopener"':''; }
  /* A CTA can point at a url, the booking modal, the Calendly modal or the
     photographer list. Without JS it still works as a plain link. */
  function act(o){
    if(!o) return {href:'#',attr:''};
    if(o.booking) return {href:(D.booking&&D.booking.base)||'#',
      attr:' data-booking="'+esc(o.booking)+'"'+(o.provider?' data-provider="'+esc(o.provider)+'"':'')};
    if(o.consult) return {href:'#contact',
      attr:' data-consult="'+esc(typeof o.consult==='string'?o.consult:'1')+'"'};
    if(o.photographers) return {href:'#photography', attr:' data-photographers="1"'};
    return {href:o.href||'#', attr:ext(o.href||'')};
  }
  function btn(o,c){ if(!o) return ''; var a=act(o);
    return '<a class="btn '+c+' fade" href="'+esc(a.href)+'"'+a.attr+'>'+esc(o.label)+' '+ar+'</a>'; }
  function lines(a){ return (a||[]).map(esc).join('<br>'); }
  function headline(a,punct){
    var l=(a||[]).slice(), last=esc(l.pop()||'');
    var out=l.map(function(x){ return '<span class="ln"><span>'+esc(x)+'</span></span>'; }).join('');
    var dot=punct==='?'?'<span class="dot dot--q">?</span>':'<span class="dot">.</span>';
    return out+'<span class="ln"><span>'+last+dot+'</span></span>';
  }

  
  if(document.readyState==='loading')
    document.addEventListener('DOMContentLoaded', boot);
  else boot();

  function boot(){
/* ================= behaviour ================= */
    var header=document.getElementById('header'), progress=document.getElementById('progress');
    function onScroll(){
      header.classList.toggle('is-stuck', window.scrollY>40);
      var h=document.documentElement.scrollHeight-window.innerHeight;
      progress.style.width=(h>0?(window.scrollY/h)*100:0)+'%';
      var m=document.getElementById('mcta'), c=document.getElementById('contact');
      if(m){
        // pages without a closing contact band (Privacy, Terms) just keep it on
        var ft=c?c.getBoundingClientRect().top:Infinity;
        m.classList.toggle('is-on', window.scrollY>600 && ft>window.innerHeight*0.6);
      }
    }
    onScroll(); window.addEventListener('scroll', onScroll, {passive:true});

    var burger=document.getElementById('burger'), drawer=document.getElementById('drawer');
    function setDrawer(o){ drawer.classList.toggle('is-open',o); burger.setAttribute('aria-expanded',o?'true':'false'); document.body.style.overflow=o?'hidden':''; }
    burger.addEventListener('click',function(){ setDrawer(true); });
    document.getElementById('drawer-close').addEventListener('click',function(){ setDrawer(false); });
    drawer.querySelectorAll('a').forEach(function(a){ a.addEventListener('click',function(){ setDrawer(false); }); });

    var grid=document.getElementById('pod-grid');
    document.querySelectorAll('.circ').forEach(function(b){
      b.addEventListener('click',function(){ var c=grid.querySelector('.pod'); if(c) grid.scrollBy({left:(c.offsetWidth+16)*Number(b.dataset.dir),behavior:'smooth'}); });
    });

    /* ------------------------------------------------------------------
       Controlled auto-advance for the room and full-episode rails.

       Alive, not restless: one step every 5s, paused the moment the user
       touches it and for 9s after they stop, off entirely under
       prefers-reduced-motion, and off while a modal is open or the tab is
       hidden. It drives the native scroll container, so there is no slider
       library and the rail still swipes by hand exactly as before.

       Reels are deliberately NOT in this list — they stay user-driven.
    ------------------------------------------------------------------ */
    function carousel(rail){
      if(!rail) return;
      var items=rail.children, STEP=5000, RESUME=9000, timer=null, idle=null, dead=false;
      function many(){ return rail.scrollWidth - rail.clientWidth > 8; }
      function go(){
        if(dead || !many() || document.hidden || document.body.style.overflow==='hidden') return;
        var w=items[0]?items[0].offsetWidth+parseFloat(getComputedStyle(rail).columnGap||10):0;
        if(!w) return;
        var last=rail.scrollWidth-rail.clientWidth-4;
        rail.scrollTo({left: rail.scrollLeft>=last?0:rail.scrollLeft+w, behavior:'smooth'});
        dots();
      }
      function start(){ stop(); timer=setInterval(go, STEP); }
      function stop(){ if(timer){ clearInterval(timer); timer=null; } }
      function hold(){              /* the user took over */
        stop(); clearTimeout(idle);
        idle=setTimeout(function(){ if(dead) return; go(); start(); }, RESUME);
      }
      ['pointerdown','touchstart','wheel','keydown'].forEach(function(ev){
        rail.addEventListener(ev, hold, {passive:true});
      });
      rail.addEventListener('mouseenter', stop);
      rail.addEventListener('mouseleave', function(){ if(!dead) hold(); });
      rail.addEventListener('scroll', dots, {passive:true});
      document.addEventListener('visibilitychange', function(){
        if(document.hidden) stop(); else if(!dead) start();
      });

      /* position dots, so a phone knows there is more than one card */
      var nav=null, buttons=[];
      function dots(){
        if(!many()){ if(nav) nav.hidden=true; return; }
        if(!nav){
          nav=document.createElement('div');
          nav.className='rail-dots'; nav.setAttribute('role','tablist');
          for(var i=0;i<items.length;i++){
            var d=document.createElement('button');
            d.type='button'; d.className='rail-dot';
            d.setAttribute('aria-label','Go to item '+(i+1));
            (function(n){ d.addEventListener('click',function(){
              hold();
              var w=items[0].offsetWidth+parseFloat(getComputedStyle(rail).columnGap||10);
              rail.scrollTo({left:n*w, behavior:'smooth'});
            }); })(i);
            nav.appendChild(d); buttons.push(d);
          }
          rail.parentNode.insertBefore(nav, rail.nextSibling);
        }
        nav.hidden=false;
        var w=items[0].offsetWidth+parseFloat(getComputedStyle(rail).columnGap||10);
        var at=Math.round(rail.scrollLeft/w);
        buttons.forEach(function(b,i){
          b.classList.toggle('is-on', i===at);
          b.setAttribute('aria-selected', i===at?'true':'false');
        });
      }

      if(REDUCE){ dead=true; dots(); return; }   /* manual only, dots stay */
      dots(); start();
    }
    carousel(document.querySelector('.rooms'));
    carousel(document.getElementById('pod-grid'));
    carousel(document.getElementById('episode-rail'));

    /* ------------------------------------------------------------------
       Room photo gallery. Opens inside KLIP — the visitor never leaves the
       site. Swipe on a phone, arrows and keyboard on a desktop, a 1 / 4
       counter throughout, arrows, swipe, the keyboard, and a thumbnail
       strip so every photo in the room is visible and one tap away rather
       than hidden behind a gesture.

       The big images are created only when the gallery opens, and only the
       current one plus its neighbours are given a src, so a room with
       twelve photos still costs nothing on page load. Thumbnails load at
       480px, not full size.
    ------------------------------------------------------------------ */
    (function(){
      var gal=document.getElementById('gallery'); if(!gal) return;
      var track=document.getElementById('gal-track'),
          nameEl=document.getElementById('gal-name'),
          countEl=document.getElementById('gal-count'),
          thumbs=document.getElementById('gal-thumbs'),
          prev=document.getElementById('gal-prev'),
          next=document.getElementById('gal-next'),
          shots=[], at=0, opener=null;

      /* Each shot is [full, alt, thumb, phone]. The last two are optional,
         so a gallery written before the resized sets existed still works. */
      function bigOf(s){
        return (window.innerWidth<=760 && s[3]) ? s[3] : s[0];
      }

      function paint(){
        countEl.textContent=(at+1)+' / '+shots.length;
        [].forEach.call(track.children,function(fig,i){
          var img=fig.firstChild, near=Math.abs(i-at)<=1;
          if(near && !img.getAttribute('src')) img.src=img.dataset.src;
          fig.classList.toggle('is-on', i===at);
        });
        [].forEach.call(thumbs.children,function(b,i){
          var on=i===at;
          b.classList.toggle('is-on', on);
          b.setAttribute('aria-current', on?'true':'false');
          if(on) b.scrollIntoView({block:'nearest', inline:'nearest'});
        });
        prev.disabled = next.disabled = shots.length<2;
      }
      function show(n){ at=(n+shots.length)%shots.length; paint(); }
      function open(list,name,from){
        shots=list; at=0; opener=from||null;
        nameEl.textContent=name||'';
        track.innerHTML=''; thumbs.innerHTML='';
        shots.forEach(function(s,i){
          var fig=document.createElement('figure'), img=document.createElement('img');
          img.alt=s[1]||''; img.dataset.src=bigOf(s);
          img.decoding='async'; img.loading='lazy';
          fig.appendChild(img); track.appendChild(fig);

          /* One thumbnail per photo, so every photo in the room is visible
             and reachable in one tap. 480px wide, not the original. */
          var t=document.createElement('button'), ti=document.createElement('img');
          t.type='button'; t.className='gal-thumb';
          t.setAttribute('aria-label','Photo '+(i+1)+' of '+shots.length);
          ti.src=s[2]||s[0]; ti.alt=''; ti.decoding='async'; ti.loading='lazy';
          t.appendChild(ti); thumbs.appendChild(t);
          t.addEventListener('click',function(){ show(i); });
        });
        /* A single photo needs no strip and no arrows. */
        thumbs.hidden = shots.length<2;
        paint();
        gal.classList.add('is-open');
        document.body.style.overflow='hidden';
        document.getElementById('gal-close').focus();
      }
      function close(){
        gal.classList.remove('is-open'); document.body.style.overflow='';
        track.innerHTML=''; thumbs.innerHTML=''; shots=[];
        if(opener){ opener.focus(); opener=null; }
      }
      window.klipGallery=open;   /* so other sections can open a room gallery */

      document.addEventListener('click',function(e){
        var b=e.target.closest('[data-gallery]'); if(!b) return;
        e.preventDefault();
        var list; try{ list=JSON.parse(b.dataset.gallery); }catch(err){ return; }
        if(list && list.length) open(list, b.dataset.galleryName||'', b);
      });
      prev.addEventListener('click',function(){ show(at-1); });
      next.addEventListener('click',function(){ show(at+1); });
      document.getElementById('gal-close').addEventListener('click',close);
      gal.addEventListener('click',function(e){
        if(e.target===gal||e.target===track) close();
      });
      document.addEventListener('keydown',function(e){
        if(!gal.classList.contains('is-open')) return;
        if(e.key==='Escape') close();
        else if(e.key==='ArrowLeft') show(at-1);
        else if(e.key==='ArrowRight') show(at+1);
      });
      /* swipe */
      var x0=null;
      track.addEventListener('touchstart',function(e){ x0=e.touches[0].clientX; },{passive:true});
      track.addEventListener('touchend',function(e){
        if(x0===null) return;
        var dx=e.changedTouches[0].clientX-x0; x0=null;
        if(Math.abs(dx)>45) show(at+(dx<0?1:-1));
      },{passive:true});
    })();

    /* ------------------------------------------------------------------
       Specials pop-up. One reusable component driven entirely from the
       admin — there is no per-promotion code.

       The rules it enforces, from the master doc: never on load, never
       over a booking or consultation modal, never on Privacy or Terms,
       once every N days per visitor, dismissal remembered, and a compact
       sheet on mobile rather than a full-screen takeover. It appears
       after a delay OR a scroll depth, whichever the visitor reaches
       first, and only once per page view.
    ------------------------------------------------------------------ */
    (function(){
      var S = D.special;
      if(!S || !S.popup) return;
      var host=document.getElementById('special'); if(!host) return;
      if(/\/(privacy|terms)\.html$/i.test(location.pathname)) return;

      var KEY='klip.sp.'+(S.id||'offer');
      try{
        var seen=localStorage.getItem(KEY);
        if(seen && (Date.now()-Number(seen)) < (S.days||7)*864e5) return;
      }catch(e){}           /* private mode: show it, do not crash */

      var box=document.getElementById('sp-box'), shown=false, armed=true;

      function build(){
        var img = (window.matchMedia('(max-width:760px)').matches &&
                   S.imageMobile) ? S.imageMobile : S.image;
        var price='';
        if(S.promoPrice){
          price='<p class="sp-price">'+
            (S.regularPrice?'<s>'+esc(S.regularPrice)+'</s> ':'')+
            '<b>'+esc(S.promoPrice)+'</b></p>';
        }
        var mail='';
        if(S.email){
          mail='<form class="sp-mail" id="sp-mail"><label class="sr-only" '+
               'for="sp-email">Email</label>'+
               '<input id="sp-email" type="email" name="email" required '+
               'autocomplete="email" placeholder="you@example.com">'+
               '<button type="submit" class="btn btn--outline">'+
               esc(S.emailLabel||'Send Me KLIP Specials')+'</button>'+
               (S.emailNote?'<span class="sp-note">'+esc(S.emailNote)+'</span>':'')+
               '</form>';
        }
        box.insertAdjacentHTML('beforeend',
          (img?'<div class="sp-img"><img src="'+esc(img)+'" alt="'+
               esc(S.imageAlt||'')+'" loading="lazy" decoding="async"></div>':'')+
          '<div class="sp-copy">'+
          (S.badge?'<span class="sp-badge">'+esc(S.badge)+'</span>':'')+
          '<h2 id="sp-head">'+esc(S.headline)+'</h2>'+
          (S.copy?'<p class="sp-text">'+esc(S.copy)+'</p>':'')+
          price+
          '<a class="btn btn--dark sp-cta" href="'+esc(D.booking&&D.booking.base||'#')+
            '"'+(S.booking?' data-booking="'+esc(S.booking)+'"':'')+'>'+
            esc(S.ctaLabel)+' <span class="ar" aria-hidden="true">&#8594;</span></a>'+
          mail+'</div>');
      }
      function esc(v){ return String(v==null?'':v)
        .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
        .replace(/"/g,'&quot;'); }

      function open(){
        if(shown || !armed) return;
        /* never on top of a booking, consultation or gallery modal */
        if(document.body.style.overflow==='hidden') return;
        shown=true; build();
        host.hidden=false;
        requestAnimationFrame(function(){ host.classList.add('is-open'); });
        document.getElementById('sp-close').focus();
        if(window.klipTrack) window.klipTrack('special_impression',
          {offer:S.name||S.headline});
      }
      function close(taken){
        host.classList.remove('is-open');
        try{ localStorage.setItem(KEY, String(Date.now())); }catch(e){}
        if(!taken && window.klipTrack) window.klipTrack('special_close',
          {offer:S.name||S.headline});
        setTimeout(function(){ host.hidden=true; }, 260);
      }

      var t=setTimeout(open, Math.max(4, S.delay||10)*1000);
      function onScroll(){
        var h=document.documentElement.scrollHeight-window.innerHeight;
        if(h>0 && (window.scrollY/h)*100 >= (S.scroll||40)){
          window.removeEventListener('scroll', onScroll);
          open();
        }
      }
      window.addEventListener('scroll', onScroll, {passive:true});

      document.getElementById('sp-close').addEventListener('click',
        function(){ close(false); });
      host.addEventListener('click', function(e){ if(e.target===host) close(false); });
      document.addEventListener('keydown', function(e){
        if(e.key==='Escape' && host.classList.contains('is-open')) close(false);
      });
      /* booking from the offer counts as taken, not dismissed-and-forgotten */
      host.addEventListener('click', function(e){
        if(e.target.closest('.sp-cta')){
          if(window.klipTrack) window.klipTrack('special_cta',
            {offer:S.name||S.headline, service:S.booking||''});
          close(true);
        }
      });
      if(S.email){
        host.addEventListener('submit', function(e){
          var f=e.target.closest('#sp-mail'); if(!f) return;
          e.preventDefault();
          var v=f.querySelector('#sp-email').value;
          fetch('/api/lead', {method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({email:v, source:'specials-popup',
                                 offer:S.name||S.headline, consent:true,
                                 page:location.pathname})})
            .catch(function(){});
          f.innerHTML='<span class="sp-note">Thanks — we\\u2019ll send the next one.</span>';
        });
      }
      document.addEventListener('click', function(e){
        if(e.target.closest('[data-booking],[data-consult]')){ armed=false; clearTimeout(t); }
      }, true);
    })();

    /* ------------------------------------------------------------------
       Conversion tracking (KLIP_FINAL §23).

       Everything is pushed to window.dataLayer, so GTM can route it to
       GA4 and to ad platforms without this file knowing about either.
       If no container is installed the pushes land in an array nobody
       reads — harmless, and nothing is sent anywhere.

       Events are named for the action, not the element, and carry the
       room or photographer so KLIP can see which room earns bookings:
         book_studio · book_room · book_photographer · rent_studio
         consultation · view_photos · explore_room · view_work · watch
         special_impression · special_close · special_cta · special_signup

       These fire when the control is clicked. A click is interest, not a
       completed booking — booking completion has to come from SimplyBook
       itself, and is not claimed here.
    ------------------------------------------------------------------ */
    window.dataLayer = window.dataLayer || [];
    /* A CTA carries both the desktop and the phone label, so textContent
       would report "Book The StudioBook Studio". Read the full label when
       the pair is present. */
    function labelOf(el){
      var f = el.querySelector && el.querySelector('.lbl-full');
      var t = (f ? f.textContent : (el.textContent || ''));
      return t.replace(/\s+/g, ' ').replace(/\s*\u2192\s*$/, '').trim().slice(0, 40);
    }
    function track(event, extra){
      try{
        var o = {event: 'klip_' + event, page: location.pathname};
        if(extra) for(var k in extra){ if(extra[k]) o[k] = extra[k]; }
        window.dataLayer.push(o);
      }catch(e){}
    }
    window.klipTrack = track;

    document.addEventListener('click', function(e){
      var el = e.target.closest('[data-track],[data-booking],[data-consult],'
                              + '[data-photographers],[data-video]');
      if(!el) return;

      var named = el.getAttribute('data-track');
      if(named){
        track(named, {room: el.getAttribute('data-track-room') || '',
                      label: labelOf(el)});
        return;
      }
      if(el.hasAttribute('data-consult')){
        track('consultation', {topic: el.getAttribute('data-consult')});
        return;
      }
      if(el.hasAttribute('data-photographers')){
        track('book_photographer', {source: 'list'});
        return;
      }
      if(el.hasAttribute('data-video')){
        track('watch', {title: ((el.querySelector('h3') || {}).textContent || '').trim()});
        return;
      }
      if(el.hasAttribute('data-booking')){
        var key = el.getAttribute('data-booking');
        var map = {photoStudioRental: 'rent_studio',
                   photographySessions: 'book_photographer'};
        track(map[key] || 'book_studio',
              {service: key, provider: el.getAttribute('data-provider') || '',
               label: labelOf(el)});
      }
    }, true);

    /* View Work links, which are ordinary anchors */
    document.addEventListener('click', function(e){
      var a = e.target.closest('a[href$="work.html"],a[href*="work.html#"]');
      if(a && !a.hasAttribute('data-track')) track('view_work', {});
    }, true);

    /* lightbox — no iframe exists until a card is clicked */
    var lb=document.getElementById('lightbox'), lbInner=document.getElementById('lb-inner');
    function ytEmbed(u){ var m=String(u).match(/(?:v=|youtu\.be\/|embed\/|shorts\/)([A-Za-z0-9_-]{6,})/); return m?'https://www.youtube.com/embed/'+m[1]+'?autoplay=1&rel=0':''; }
    function closeLb(){ lb.classList.remove('is-open'); var f=lbInner.querySelector('iframe'); if(f) f.remove(); document.body.style.overflow=''; }
    document.addEventListener('click',function(e){
      var card=e.target.closest('[data-video]'); if(!card) return;
      var src=ytEmbed(card.dataset.video); if(!src) return;
      e.preventDefault();
      var f=document.createElement('iframe'); f.src=src; f.allow='autoplay; encrypted-media; picture-in-picture'; f.allowFullscreen=true;
      lbInner.appendChild(f); lb.classList.add('is-open'); document.body.style.overflow='hidden';
      document.getElementById('lb-close').focus();
    });
    document.getElementById('lb-close').addEventListener('click',closeLb);
    lb.addEventListener('click',function(e){ if(e.target===lb) closeLb(); });
    document.addEventListener('keydown',function(e){ if(e.key==='Escape'){ closeLb(); setDrawer(false); } });

    /* ---------- KLIP Visibility Check ---------- */
    (function(){
      var form=document.getElementById('vis-form'), out=document.getElementById('vis-out'),
          input=document.getElementById('vis-url'), go=document.getElementById('vis-go');
      if(!form) return;
      var busy=false;
      function track(ev,data){ try{ (window.dataLayer=window.dataLayer||[]).push(Object.assign({event:ev},data||{})); }catch(e){} }
      function band(n){ return n>=80?'Strong':n>=60?'Fair':n>=40?'Needs work':'Weak'; }
      function msg(html){ out.classList.add('is-on'); out.innerHTML='<p class="vis-msg">'+html+'</p>'; }

      function render(d){
        var scores=(D.visibility.areas||[]).map(function(a){
          var s=Math.max(0,Math.min(100,Math.round((d.scores&&d.scores[a.key])||0)));
          return '<div class="score"><b>'+esc(a.label)+'</b>'+
            '<span class="num">'+s+'<i>/100 · '+esc(band(s))+'</i></span>'+
            '<span class="bar'+(s<60?' warn':'')+'"><i style="width:'+s+'%"></i></span></div>';
        }).join('');
        var warn='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17h.01"/></svg>';
        var ok='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 12l5 5L20 6"/></svg>';
        var items=(d.findings||[]).slice(0,6).map(function(f){
          return '<li>'+(f.ok?ok:warn)+'<span><span class="t">'+esc(f.ok?'OK':'Fix')+' —</span>'+esc(f.text)+'</span></li>';
        }).join('');
        out.classList.add('is-on');
        out.innerHTML='<div class="vis-scores">'+scores+'</div>'+
          (items?'<ul class="findings">'+items+'</ul>':'')+
          '<div class="vis-lead"><h3>'+esc(D.visibility.leadHeadline)+'</h3><p>'+esc(D.visibility.leadBody)+'</p>'+
          '<form id="vis-lead-form"><input name="name" placeholder="Name" autocomplete="name" required>'+
          '<input name="company" placeholder="Company" autocomplete="organization">'+
          '<input name="email" type="email" placeholder="Email" autocomplete="email" required>'+
          '<input name="phone" placeholder="Phone (optional)" autocomplete="tel">'+
          '<button class="btn btn--solid" type="submit">'+esc(D.visibility.leadCta)+' '+ar+'</button></form>'+
          '<p class="vis-msg" id="vis-lead-msg" hidden></p></div>';

        var lf=document.getElementById('vis-lead-form');
        lf.addEventListener('submit', function(e){
          e.preventDefault();
          var fd={}; new FormData(lf).forEach(function(v,k){ fd[k]=v; });
          fd.url=d.url; fd.scores=d.scores;
          var m=document.getElementById('vis-lead-msg'); m.hidden=false; m.textContent='Sending…';
          fetch(D.visibility.leadEndpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(fd)})
            .then(function(r){ if(!r.ok) throw 0; m.textContent='Got it. We will come back to you with the full plan.'; track('audit_lead_submitted',{url:d.url}); })
            .catch(function(){ m.textContent='We could not send that just now — email info@theklipstudio.com and we will pick it up.'; });
        });
      }

      form.addEventListener('submit', function(e){
        e.preventDefault();
        if(busy) return;
        var raw=(input.value||'').trim();
        if(!raw){ input.focus(); return; }
        if(!/^https?:\/\//i.test(raw)) raw='https://'+raw;
        var host;
        try{ host=new URL(raw).hostname; }catch(err){ msg('That does not look like a website address. Try something like <strong>yourbusiness.com</strong>.'); return; }
        if(!/\./.test(host)){ msg('That does not look like a website address. Try something like <strong>yourbusiness.com</strong>.'); return; }

        busy=true; go.disabled=true;
        var label=go.innerHTML; go.innerHTML='<span class="vis-spin" aria-hidden="true"></span> Scanning';
        msg('Scanning <strong>'+esc(host)+'</strong> — this takes a few seconds.');
        track('audit_started',{url:host});

        fetch(D.visibility.endpoint,{
          method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({url:raw})
        })
        .then(function(r){ return r.json().then(function(j){ if(!r.ok) throw j; return j; }); })
        .then(function(d){ render(d); track('audit_completed',{url:host}); })
        .catch(function(err){
          track('audit_failed',{url:host});
          var reason=(err&&err.error)||'';
          if(reason){ msg(esc(reason)); }
          else{
            msg('The scanner is not reachable from this preview. It runs as a server function on the live site '+
                '(<code>/api/visibility</code>) — once KLIP is deployed to Cloudflare Pages this returns a real result. '+
                'No scores are shown here because inventing them would be worse than showing none.');
          }
        })
        .then(function(){ busy=false; go.disabled=false; go.innerHTML=label; });
      });
    })();


    /* ================= BOOKING / CONSULTATION / PHOTOGRAPHER MODALS =================
       Nothing here loads until a visitor clicks. SimplyBook and Calendly are
       embedded inside KLIP; the external page is a fallback only. ============== */
    (function(){
      var B=D.booking||{config:{}}, CN=D.consultation||{}, PG=D.photographers||{items:[]};
      var mBooking=document.getElementById('booking-modal'),
          mConsult=document.getElementById('consult-modal'),
          mPhoto  =document.getElementById('pg-modal');
      var lastFocus=null, openEl=null;

      function focusables(el){
        return [].slice.call(el.querySelectorAll('a[href],button:not([disabled]),input,select,textarea,iframe,[tabindex]:not([tabindex="-1"])'))
          .filter(function(n){ return n.offsetParent!==null || n.tagName==='IFRAME'; });
      }
      function trap(e){
        if(!openEl || e.key!=='Tab') return;
        var f=focusables(openEl); if(!f.length) return;
        var first=f[0], last=f[f.length-1];
        if(e.shiftKey && document.activeElement===first){ e.preventDefault(); last.focus(); }
        else if(!e.shiftKey && document.activeElement===last){ e.preventDefault(); first.focus(); }
      }
      function open(el){
        lastFocus=document.activeElement; openEl=el;
        el.classList.add('is-open'); document.body.style.overflow='hidden';
        var c=el.querySelector('[data-mdl-close]'); if(c) c.focus();
        document.addEventListener('keydown', trap);
      }
      function close(){
        if(!openEl) return;
        openEl.classList.remove('is-open');
        // tear the embed down so nothing keeps loading or playing in the background
        var body=openEl.querySelector('.mdl-body'); if(body) body.innerHTML='';
        document.body.style.overflow='';
        document.removeEventListener('keydown', trap);
        if(lastFocus && lastFocus.focus) lastFocus.focus();
        openEl=null;
      }
      document.addEventListener('click', function(e){
        if(e.target.closest('[data-mdl-close]')) { close(); return; }
        if(openEl && e.target===openEl) close();
      });
      document.addEventListener('keydown', function(e){ if(e.key==='Escape') close(); });

      /* ---- booking ---- */
      /* a room name used as a booking key resolves to its configured service */
      function resolveKey(key){ return ((B.aliases||{})[key]) || key; }

      function bookingUrl(key, provider){
        var cfg=(B.config||{})[resolveKey(key)]||{}, base=B.base||'';
        if(!base) return '';
        var u=base.replace(/\/+$/,'');
        // deep-link segments are appended only when a verified id exists
        var prov = provider ? 'provider:'+encodeURIComponent(provider)+'/' : '';
        if(cfg.serviceId)  return u+'/#book/service:'+encodeURIComponent(cfg.serviceId)+'/count:1/'+prov;
        if(cfg.categoryId) return u+'/#book/category:'+encodeURIComponent(cfg.categoryId)+'/'+prov;
        if(prov)           return u+'/#book/'+prov;
        return u+'/';
      }

      /* The official SimplyBook website widget, when the company login
         has been filled in. It renders inside the KLIP modal — same
         chrome, same header, no redirect. Returns false if unavailable
         so the caller can embed the booking page instead. */
      var sbScript=null;
      function simplybookWidget(host, key, provider){
        var w=B.widget||{};
        if(!w.company || !w.script) return false;
        var cfg=(B.config||{})[resolveKey(key)]||{};
        var opts={
          widget_type:'iframe',
          url:'https://'+w.company+'.simplybook.me',
          theme:w.theme||'',
          theme_settings:w.themeSettings||{},
          timeline:'modern',
          datepicker:'top_calendar',
          app_config:{ clear_session:0, allow_switch_to_ada:0, predefined:{} }
        };
        if(cfg.serviceId)  opts.app_config.predefined.service  = cfg.serviceId;
        if(cfg.categoryId) opts.app_config.predefined.category = cfg.categoryId;
        if(provider)       opts.app_config.predefined.provider = provider;
        function go(){
          try{ host.innerHTML=''; new window.SimplybookWidget(Object.assign({container_id:host.id}, opts)); }
          catch(e){ return false; }
        }
        if(window.SimplybookWidget){ go(); return true; }
        if(!sbScript){
          sbScript=document.createElement('script');
          sbScript.src=(w.script.indexOf('//')===0?'https:':'')+w.script;
          sbScript.async=true;
          document.head.appendChild(sbScript);
        }
        sbScript.addEventListener('load', go);
        return true;
      }

      function openBooking(key, provider){
        var cfg=(B.config||{})[resolveKey(key)]||{}, url=bookingUrl(key, provider);
        document.getElementById('booking-title').textContent=cfg.title||B.title||'Book with KLIP';
        document.getElementById('booking-note').textContent=B.note||'';
        var fb=document.getElementById('booking-fallback');
        fb.textContent=B.fallbackLabel||'Open booking in a new tab'; fb.href=url||'#';
        var body=document.getElementById('booking-body');
        body.innerHTML='<div class="mdl-state"><span class="mdl-load" aria-hidden="true"></span>'+
          '<p style="margin-top:14px">Loading secure booking…</p></div>';
        open(mBooking);
        if(!url){
          body.innerHTML='<div class="mdl-state"><h3>Booking is not connected yet</h3>'+
            '<p>The SimplyBook.me booking link has not been added to this build.</p></div>';
          return;
        }
        /* preferred: the official SimplyBook widget inside this modal */
        body.innerHTML='<div id="sb-widget" class="mdl-widget"></div>';
        if(simplybookWidget(document.getElementById('sb-widget'), key, provider)){
          track('booking_modal_opened',{key:key,provider:provider||'',mode:'widget'});
          return;
        }

        var loaded=false;
        var f=document.createElement('iframe');
        f.className='mdl-frame'; f.title=(cfg.title||'KLIP')+' booking';
        f.setAttribute('loading','eager'); f.setAttribute('allow','payment');
        f.src=url;
        f.addEventListener('load', function(){ loaded=true; });
        body.innerHTML=''; body.appendChild(f);
        // some providers refuse to be framed — offer the fallback rather than a blank box
        setTimeout(function(){
          if(loaded || openEl!==mBooking) return;
          body.innerHTML='<div class="mdl-state"><h3>Opening booking in a new tab</h3>'+
            '<p>The booking system would not load inside this window. Your booking and payment still go to KLIP.</p>'+
            '<a class="btn btn--dark" href="'+url+'" target="_blank" rel="noopener">Continue to booking <span class="ar" aria-hidden="true">&#8594;</span></a></div>';
        }, 6000);
        track('booking_modal_opened',{key:key,provider:provider||'',mode:'embed'});
      }

      /* ---- consultation (Calendly) ----
         Calendly's own inline embed, styled with the supported colour
         parameters and with the duplicate event header hidden, so the
         scheduler sits inside the KLIP modal rather than on calendly.com. */
      var calScript=null;
      function calendlyUrlFor(topic){
        var base=(topic && (CN.events||{})[topic]) || CN.calendlyUrl || '';
        if(!base) return '';
        var q=[], br=CN.brand||{};
        if(CN.hideEventDetails!==false) q.push('hide_event_type_details=1');
        q.push('hide_gdpr_banner=1');
        if(br.background) q.push('background_color='+br.background);
        if(br.text)       q.push('text_color='+br.text);
        if(br.primary)    q.push('primary_color='+br.primary);
        return base + (base.indexOf('?')>-1?'&':'?') + q.join('&');
      }
      function calendlyInline(host, url){
        if(CN.inlineEmbed===false) return false;
        function go(){
          if(!window.Calendly) return false;
          try{ host.innerHTML=''; window.Calendly.initInlineWidget({url:url, parentElement:host}); }
          catch(e){ return false; }
        }
        if(window.Calendly){ go(); return true; }
        if(!calScript){
          calScript=document.createElement('script');
          calScript.src='https://assets.calendly.com/assets/external/widget.js';
          calScript.async=true;
          document.head.appendChild(calScript);
        }
        calScript.addEventListener('load', go);
        return true;
      }
      function openConsult(topic){
        document.getElementById('consult-title').textContent=CN.title||'Book a call';
        var body=document.getElementById('consult-body');
        open(mConsult);
        if(!calendlyUrlFor(topic)){
          body.innerHTML='<div class="mdl-state">'+
            '<p>'+esc(CN.intro||'')+'</p>'+
            '<p>The online scheduler is not connected yet — reach us directly and we will get it booked.</p>'+
            (CN.phone?'<a class="btn btn--dark" href="tel:'+esc(CN.phone.replace(/[^0-9+]/g,''))+'">Call '+esc(CN.phone)+' <span class="ar" aria-hidden="true">&#8594;</span></a>':'')+
            (CN.email?'<a class="btn btn--outline" href="mailto:'+esc(CN.email)+'">Email KLIP <span class="ar" aria-hidden="true">&#8594;</span></a>':'')+
            '</div>';
          return;
        }
        var cUrl=calendlyUrlFor(topic);
        body.innerHTML='<div id="cal-inline" class="mdl-widget"></div>';
        if(calendlyInline(document.getElementById('cal-inline'), cUrl)){
          track('consultation_modal_opened',{topic:topic||'',mode:'inline'});
          return;
        }
        var f=document.createElement('iframe');
        f.className='mdl-frame'; f.title='KLIP consultation scheduler'; f.src=cUrl;
        body.innerHTML=''; body.appendChild(f);
        track('consultation_modal_opened',{topic:topic||'',mode:'embed'});
      }

      /* ---- photographers ---- */
      function openPhotographers(){
        document.getElementById('pg-title').textContent=PG.title||'Photographers';
        var fa=PG.firstAvailable||{};
        document.getElementById('pg-body').innerHTML=
          '<div class="pg-list">'+(PG.items||[]).map(function(x){
            /* a face first: the headshot when there is one, the
               photographer's initials in the KLIP palette until then */
            var initials=String(x.name||'').replace(/—.*$/,'').trim().split(/\s+/)
                           .slice(0,2).map(function(w){ return w.charAt(0); }).join('').toUpperCase();
            var face = x.headshot
              ? '<div class="pg-face">'+pic(x.headshot, x.name, 'loading="lazy" decoding="async"')+'</div>'
              : '<div class="pg-face pg-face--empty" aria-hidden="true"><span>'+esc(initials)+'</span></div>';
            return '<div class="pg">'+face+'<b>'+esc(x.name)+'</b><span class="sp">'+esc(x.specialties)+'</span>'+
              '<p>'+esc(x.bio)+'</p>'+
              '<a class="btn btn--dark" href="'+esc(B.base||'#')+'" data-booking="'+esc(x.booking||'photographySessions')+'"'+
            (x.providerId?' data-provider="'+esc(x.providerId)+'"':'')+'>'+
              esc(PG.cta||'Book')+' <span class="ar" aria-hidden="true">&#8594;</span></a></div>';
          }).join('')+'</div>'+
          (fa.title?'<div class="pg-first"><div><b>'+esc(fa.title)+'</b><span>'+esc(fa.text||'')+'</span></div>'+
            '<a class="btn btn--ghost" href="'+esc(B.base||'#')+'" data-booking="'+esc(fa.booking||'photographySessions')+'">'+
            esc(fa.cta||'Find a time')+' <span class="ar" aria-hidden="true">&#8594;</span></a></div>':'')+
          (PG.intro?'<p class="pg-note">'+esc(PG.intro)+'</p>':'');
        open(mPhoto);
      }

      function track(ev,data){ try{ (window.dataLayer=window.dataLayer||[]).push(Object.assign({event:ev},data||{})); }catch(e){} }

      /* one delegated listener for every trigger on the page, including the
         ones rendered inside a modal */
      document.addEventListener('click', function(e){
        var t=e.target.closest('[data-booking],[data-consult],[data-photographers]');
        if(!t) return;
        e.preventDefault();
        if(t.hasAttribute('data-booking')){
          var key=t.getAttribute('data-booking');
          var prov=t.getAttribute('data-provider')||'';
          if(openEl) { close(); setTimeout(function(){ openBooking(key, prov); }, 60); }
          else openBooking(key, prov);
        }
        else if(t.hasAttribute('data-consult')){
          var topic=t.getAttribute('data-consult');
          openConsult(topic==='1'?'':topic);
        }
        else openPhotographers();
      });
    })();

    /* ---------- silent previews ----------
       A card ships as a poster. Its video source is attached only when the
       card is near the viewport, nothing is preloaded, and exactly one
       preview plays at a time: on hover on desktop, on becoming the centred
       card on a phone. prefers-reduced-motion gets the poster and nothing
       else. */
    (function(){
      if(REDUCE) return;
      var cards=[].slice.call(document.querySelectorAll('[data-preview],[data-preview-mp4]'));
      if(!cards.length) return;
      var playing=null;

      function build(card){
        if(card._v) return card._v;
        var v=document.createElement('video');
        v.muted=true; v.loop=true; v.playsInline=true; v.preload='none';
        v.setAttribute('muted',''); v.setAttribute('playsinline','');
        v.setAttribute('aria-hidden','true'); v.tabIndex=-1;
        [['data-preview','video/webm'],['data-preview-mp4','video/mp4']].forEach(function(p){
          var src=card.getAttribute(p[0]);
          if(src){ var so=document.createElement('source'); so.src=src; so.type=p[1]; v.appendChild(so); }
        });
        var host=card.querySelector('.pod-thumb')||card;
        host.appendChild(v); card._v=v; return v;
      }

      function stop(){
        if(!playing) return;
        try{ playing.pause(); }catch(e){}
        playing.classList.remove('is-playing');
        playing=null;
      }
      function start(card){
        var v=card._v; if(!v || v===playing) return;
        stop();
        playing=v; v.classList.add('is-playing');
        var go=v.play(); if(go&&go.catch) go.catch(function(){ v.classList.remove('is-playing'); });
      }

      /* attach the source only when the card comes close */
      var near=new IntersectionObserver(function(en){
        en.forEach(function(x){ if(x.isIntersecting){ build(x.target); near.unobserve(x.target); } });
      },{rootMargin:'250px 0px'});
      cards.forEach(function(c){ near.observe(c); });

      if(window.matchMedia('(pointer:fine)').matches){
        cards.forEach(function(c){
          c.addEventListener('mouseenter', function(){ build(c); start(c); });
          c.addEventListener('mouseleave', stop);
        });
      } else {
        /* phone: whichever card is nearest the middle of the screen plays */
        var centred=new IntersectionObserver(function(en){
          var best=null, bestRatio=0;
          en.forEach(function(x){ if(x.isIntersecting && x.intersectionRatio>bestRatio){ best=x.target; bestRatio=x.intersectionRatio; } });
          if(best && bestRatio>0.6){ build(best); start(best); }
          else if(!best) stop();
        },{threshold:[0,0.6,0.9], rootMargin:'-20% 0px -20% 0px'});
        cards.forEach(function(c){ centred.observe(c); });
      }

      document.addEventListener('visibilitychange', function(){ if(document.hidden) stop(); });
    })();

    /* ---------- Work page filters ----------
       Every project is in the HTML; this only hides the ones that do not
       match, so the page still works with JavaScript off. */
    (function(){
      var bar=document.querySelector('.work-filters'), grid=document.getElementById('work-grid');
      if(!bar||!grid) return;
      var cards=[].slice.call(grid.querySelectorAll('.w'));
      bar.addEventListener('click', function(e){
        var btn=e.target.closest('button[data-filter]'); if(!btn) return;
        var key=btn.getAttribute('data-filter');
        [].forEach.call(bar.querySelectorAll('button'), function(b){
          b.setAttribute('aria-pressed', String(b===btn));
        });
        var shown=0;
        cards.forEach(function(c){
          var on=(key==='all')||(c.getAttribute('data-category')===key);
          c.hidden=!on; if(on) shown++;
        });
        track('work_filter',{filter:key,results:shown});
      });
    })();

    /* Insights category filter — same approach: every article is in the
       HTML and this only hides the ones that do not match, so the hub
       still works with JavaScript off. */
    (function(){
      var bar=document.querySelector('.ins-filters'),
          grid=document.getElementById('ins-grid');
      if(!bar||!grid) return;
      var cards=[].slice.call(grid.querySelectorAll('.ins-card'));
      bar.addEventListener('click', function(e){
        var btn=e.target.closest('button[data-cat]'); if(!btn) return;
        var key=btn.getAttribute('data-cat');
        [].forEach.call(bar.querySelectorAll('button'), function(b){
          b.setAttribute('aria-pressed', String(b===btn));
        });
        var shown=0;
        cards.forEach(function(c){
          var on=(key==='all')||(c.getAttribute('data-cat')===key);
          c.hidden=!on; if(on) shown++;
        });
        track('insights_filter',{filter:key,results:shown});
      });
    })();

    /* ---------- reveal motion (CSS + IntersectionObserver) ---------- */
    function revealNow(sec){
      var els=sec.querySelectorAll('.ln>span, .fade');
      for(var i=0;i<els.length;i++){ els[i].style.transitionDelay=Math.min(i*0.04,.2)+'s'; }
      sec.classList.add('in');
    }
    if(REDUCE){
      document.body.classList.remove('js-motion'); document.body.classList.add('no-motion');
    } else {
      var blocks=document.querySelectorAll('section, footer, .sec-head, .svc-grid, .pod-grid, .rooms, .photo-grid, .work-grid, .ind-grid, .why-split, .about-split, .loc-panel, .studio-copy, .photo-split, .vis-panel, .hero');
      if(!('IntersectionObserver' in window)){
        blocks.forEach(revealNow);
      } else {
        var io=new IntersectionObserver(function(en){
          en.forEach(function(x){ if(x.isIntersecting){ revealNow(x.target); io.unobserve(x.target); } });
        },{rootMargin:'300px 0px 400px 0px',threshold:0});
        blocks.forEach(function(el){ io.observe(el); });
        requestAnimationFrame(function(){
          blocks.forEach(function(el){
            if(el.getBoundingClientRect().top < window.innerHeight+400){ revealNow(el); io.unobserve(el); }
          });
        });
      }
      var sweep=function(){
        var vb=window.innerHeight+400;
        blocks.forEach(function(el){ if(!el.classList.contains('in') && el.getBoundingClientRect().top<vb) revealNow(el); });
      };
      window.addEventListener('scroll', sweep, {passive:true});
      setTimeout(function(){
        document.querySelectorAll('.fade').forEach(function(el){
          var r=el.getBoundingClientRect();
          if(r.top<window.innerHeight && r.bottom>0 && parseFloat(getComputedStyle(el).opacity)<.05){
            var p=el.closest('section, footer'); if(p) p.classList.add('in');
          }
        });
      },2500);

      /* Heavy motion layer: desktop only, after first paint.
         GSAP + ScrollTrigger + Lenis are ~137KB and every effect they drive
         is already switched off below 761px, so a phone never downloads
         them. Phones use native scrolling and CSS scroll-snap. */
      var DESKTOP=window.matchMedia('(min-width:761px)').matches
                  && !window.matchMedia('(pointer:coarse)').matches;
      if(!IN_FRAME && DESKTOP && !REDUCE){
        var load=function(s){ return new Promise(function(res){ var t=document.createElement('script'); t.src=s; t.onload=res; t.onerror=res; document.body.appendChild(t); }); };
        load('js/gsap.min.js').then(function(){ return load('js/ScrollTrigger.min.js'); }).then(function(){ return load('js/lenis.min.js'); })
        .then(function(){
          if(!window.gsap||!window.ScrollTrigger) return;
          gsap.registerPlugin(ScrollTrigger);
          if(window.Lenis){
            var lenis=new Lenis({duration:1.05,easing:function(t){return Math.min(1,1.001-Math.pow(2,-10*t));},smoothWheel:true});
            lenis.on('scroll',ScrollTrigger.update);
            gsap.ticker.add(function(t){ lenis.raf(t*1000); });
            gsap.ticker.lagSmoothing(0);
            document.querySelectorAll('a[href^="#"]').forEach(function(a){
              a.addEventListener('click',function(e){ var t=document.querySelector(a.getAttribute('href')); if(t){ e.preventDefault(); lenis.scrollTo(t,{offset:-100}); } });
            });
          }
          var BIG=window.matchMedia('(min-width:761px)').matches;   // no parallax on phones
        if(BIG) gsap.utils.toArray('.location .bg img, .final .bg img, .pagehero .bg img').forEach(function(img){
            gsap.fromTo(img,{yPercent:-6},{yPercent:6,ease:'none',scrollTrigger:{trigger:img.closest('section'),start:'top bottom',end:'bottom top',scrub:true}});
          });
          if(BIG) gsap.to('.hero-media',{yPercent:12,ease:'none',scrollTrigger:{trigger:'.hero',start:'top top',end:'bottom top',scrub:true}});
          if(window.matchMedia('(pointer:fine)').matches){
            var cur=document.getElementById('cursor'), ring=document.getElementById('cursor-ring');
            var cx=gsap.quickTo(cur,'x',{duration:.18,ease:'power3'}), cy=gsap.quickTo(cur,'y',{duration:.18,ease:'power3'});
            var rx=gsap.quickTo(ring,'x',{duration:.42,ease:'power3'}), ry=gsap.quickTo(ring,'y',{duration:.42,ease:'power3'});
            window.addEventListener('mousemove',function(e){ document.body.classList.add('cursor-on'); cx(e.clientX); cy(e.clientY); rx(e.clientX); ry(e.clientY); },{passive:true});
            document.addEventListener('mouseleave',function(){ document.body.classList.remove('cursor-on'); });
            document.querySelectorAll('.pod, .w').forEach(function(el){
              el.addEventListener('mouseenter',function(){ document.body.classList.add('cursor-play'); });
              el.addEventListener('mouseleave',function(){ document.body.classList.remove('cursor-play'); });
            });
            document.querySelectorAll('.btn, .circ').forEach(function(el){
              var qx=gsap.quickTo(el,'x',{duration:.4,ease:'power3'}), qy=gsap.quickTo(el,'y',{duration:.4,ease:'power3'});
              el.addEventListener('mousemove',function(e){ var r=el.getBoundingClientRect(); qx((e.clientX-(r.left+r.width/2))*.28); qy((e.clientY-(r.top+r.height/2))*.4); });
              el.addEventListener('mouseleave',function(){ qx(0); qy(0); });
            });
          }
          ScrollTrigger.refresh();
        });
      }
    }
  }
})();
