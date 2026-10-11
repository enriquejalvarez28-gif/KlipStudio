/* ============================================================
   KLIP — interior page renderer.
   Every page other than the homepage is described as a list of
   blocks in pages.js. This file turns those blocks into markup
   using the same components and styles as the homepage, so the
   whole site stays one design system.

   Block types: pagehero · editorial · split · cards · tiles ·
                clips · steps · facts · visibility · cta
   ============================================================ */
(window.KLIPREADY||function(f){f();})(function(){
  var D=window.KLIP, P=window.KLIP_PAGES, U=window.KLIPUI;
  if(!D||!P||!U) return;

  var key=document.body.getAttribute('data-page');
  var page=P[key];
  if(!page) return;

  var esc=U.esc, btn=U.btn, act=U.act, icon=U.icon, headline=U.headline, ar=U.ar, pic=U.pic;
  var out=[];

  function ctas(list, styles){
    styles=styles||['btn--solid','btn--ghost'];
    return (list||[]).map(function(c,i){ return btn(c, styles[i]||styles[styles.length-1]); }).join('');
  }

  /* ---- page hero: compact cinematic band ---- */
  function pagehero(b){
    return '<section class="pagehero" id="top">'+
      (b.image?'<div class="bg">'+pic(b.image,b.imageAlt||'','fetchpriority="high"')+'</div><div class="scrim" aria-hidden="true"></div>':'')+
      '<div class="wrap rv">'+
        (b.eyebrow?'<p class="eyebrow on-dark fade">'+esc(b.eyebrow)+'</p>':'')+
        '<h1>'+headline(b.headline)+'</h1>'+
        (b.body?'<p class="lede on-dark fade" style="margin-top:20px">'+esc(b.body)+'</p>':'')+
        (b.ctas?'<div class="hero-actions">'+ctas(b.ctas)+'</div>':'')+
      '</div></section>';
  }

  /* ---- editorial grid: thin rules, no cards ---- */
  function editorial(b){
    return '<section class="sec sec--paper"'+(b.id?' id="'+esc(b.id)+'"':'')+'><div class="wrap">'+
      head(b)+
      '<div class="svc-grid rv">'+(b.items||[]).map(function(i){
        var tag=i.href?'a':'div', href=i.href?' href="'+esc(i.href)+'"':'';
        return '<'+tag+' class="svc fade"'+href+'>'+(i.icon?icon(i.icon):'')+
          '<h3>'+esc(i.title)+'</h3><p>'+esc(i.text)+'</p></'+tag+'>';
      }).join('')+'</div></div></section>';
  }

  /* ---- image + copy, either way round ---- */
  function split(b){
    var fig='<figure>'+pic(b.image,b.imageAlt||'','loading="lazy" decoding="async"')+'</figure>';
    var copy='<div class="studio-copy">'+
      (b.eyebrow?'<p class="eyebrow fade">'+esc(b.eyebrow)+'</p>':'')+
      '<h2>'+headline(b.headline)+'</h2>'+
      (b.body?'<p class="lede fade">'+esc(b.body)+'</p>':'')+
      (b.points?'<div class="why-points">'+b.points.map(function(p){
         return '<div class="why-point fade"><b>'+esc(p.title)+'</b><span>'+esc(p.text)+'</span></div>'; }).join('')+'</div>':'')+
      (b.ctas?'<div class="photo-actions">'+ctas(b.ctas,['btn--dark','btn--outline'])+'</div>':'')+
    '</div>';
    return '<section'+(b.id?' id="'+esc(b.id)+'"':'')+' style="background:var(--paper)">'+
      '<div class="studio-split rv">'+(b.reverse?copy+fig:fig+copy)+'</div></section>';
  }

  /* ---- image cards (rooms, categories, projects) ---- */
  function cards(b){
    var cls=b.ratio==='portrait'?'ind':'room';
    return '<section class="sec sec--paper"'+(b.id?' id="'+esc(b.id)+'"':'')+'><div class="wrap">'+
      head(b)+
      '<div class="'+(b.ratio==='portrait'?'ind-grid':'rooms')+' rv" style="'+(b.ratio==='portrait'?'':'grid-template-columns:repeat('+(b.cols||4)+',minmax(0,1fr))')+'">'+
      (b.items||[]).map(function(i){
        var a=act(i);
        if(b.ratio==='portrait'){
          return '<a class="ind fade" href="'+esc(a.href)+'"'+a.attr+'>'+pic(i.image,i.title,'loading="lazy" decoding="async"')+''+
            '<figcaption><b>'+esc(i.title)+'</b>'+(i.sub?'<span>'+esc(i.sub)+'</span>':'')+'</figcaption></a>';
        }
        return '<a class="room fade" href="'+esc(a.href)+'"'+a.attr+'><div class="room-img">'+pic(i.image,i.title,'loading="lazy" decoding="async"')+'</div>'+
          '<h3>'+esc(i.title)+'</h3>'+(i.sub?'<span>'+esc(i.sub)+'</span>':'')+'</a>';
      }).join('')+'</div></div></section>';
  }

  /* ---- rooms: image-led blocks, photo dominant, sides alternating ---- */
  function rooms(b){
    /* one list of rooms, in content.json > studio.rooms — the homepage
       tiles and these blocks both read it, so a room is edited once */
    var list=b.items;
    if(!list && b.source==='studio.rooms') list=(D.studio||{}).rooms;
    var out='<section class="sec sec--paper"'+(b.id?' id="'+esc(b.id)+'"':'')+'><div class="wrap">'+head(b)+'</div>';
    (list||[]).forEach(function(r,i){
      var a=act(r), rev=(i%2===1), name=r.name||r.title;
      var fig='<figure>'+pic(r.image, r.imageAlt||name, 'loading="lazy" decoding="async"')+'</figure>';
      var copy='<div class="studio-copy">'+
        (r.role?'<p class="eyebrow fade">'+esc(r.role)+'</p>':'')+
        '<h2>'+headline([name])+'</h2>'+
        (r.summary||r.sub?'<p class="lede fade">'+esc(r.summary||r.sub)+'</p>':'')+
        (r.capabilities&&r.capabilities.length
          ? '<ul class="room-caps fade">'+r.capabilities.map(function(c){
              return '<li>'+esc(c)+'</li>'; }).join('')+'</ul>' : '')+
        '<div class="photo-actions"><a class="btn btn--dark" href="'+esc(a.href)+'"'+a.attr+'>'+
          esc(r.cta||'Book This Room')+' <span class="ar" aria-hidden="true">&#8594;</span></a></div>'+
      '</div>';
      out+='<div class="studio-split studio-split--room'+(rev?' is-rev':'')+' rv">'+
             (rev?copy+fig:fig+copy)+'</div>';
    });
    return out+'</section>';
  }

  /* ---- numbered process ---- */
  function steps(b){
    return '<section class="sec sec--dark"'+(b.id?' id="'+esc(b.id)+'"':'')+'><div class="wrap">'+
      head(b,true)+
      '<div class="steps rv">'+(b.items||[]).map(function(i,n){
        return '<div class="step fade"><b>'+String(n+1).padStart(2,'0')+'</b><h3>'+esc(i.title)+'</h3><p>'+esc(i.text)+'</p></div>';
      }).join('')+'</div></div></section>';
  }

  /* ---- short fact rows (address, hours, contact) ---- */
  function facts(b){
    return '<section class="sec sec--paper"'+(b.id?' id="'+esc(b.id)+'"':'')+'><div class="wrap">'+
      head(b)+
      '<div class="why-points rv" style="max-width:860px">'+(b.items||[]).map(function(i){
        return '<div class="why-point fade"><b>'+esc(i.title)+'</b><span>'+(i.html||esc(i.text))+'</span></div>';
      }).join('')+'</div></div></section>';
  }

  /* ---- podcast / reel poster cards ---- */
  function clips(b){
    return '<section class="sec sec--paper"'+(b.id?' id="'+esc(b.id)+'"':'')+'><div class="wrap">'+
      head(b)+
      '<div class="pod-grid rv" id="pod-grid">'+(b.items||[]).map(function(c){
        return '<a class="pod fade" href="'+esc(c.video||'#')+'"'+(c.video?' data-video="'+esc(c.video)+'"':'')+'>'+
          '<div class="pod-thumb">'+pic(c.image,c.title,'loading="lazy" decoding="async"')+'</div>'+
          '<div class="pod-meta"><div><span class="label">'+esc(c.show||'')+'</span><h3>'+esc(c.title)+'</h3></div>'+
          (c.time?'<span class="pod-time">'+esc(c.time)+'</span>':'')+'</div></a>';
      }).join('')+'</div></div></section>';
  }

  /* ---- the Visibility Check, reused from the homepage ---- */
  function visibility(){
    var V=D.visibility;
    return '<section class="sec sec--paper" id="visibility"><div class="wrap"><div class="vis-panel rv">'+
      '<div class="vis-head"><div><h2 style="color:#fff">'+headline(V.headline,'?')+'</h2>'+
        '<p class="lede on-dark fade" style="margin-top:16px">'+esc(V.sub)+'</p></div>'+
        '<p class="vis-micro fade">'+esc(V.microLabel)+'</p></div>'+
      '<form class="vis-form fade" id="vis-form" novalidate>'+
        '<label class="skip" for="vis-url">Your website address</label>'+
        '<input id="vis-url" name="url" type="text" inputmode="url" autocomplete="url" placeholder="'+esc(V.placeholder)+'">'+
        '<button type="submit" id="vis-go">'+esc(V.button)+' '+ar+'</button></form>'+
      '<p class="vis-note fade">'+esc(V.disclaimer)+'</p>'+
      '<div class="vis-out" id="vis-out" aria-live="polite"></div></div></div></section>';
  }

  /* ---- closing band ---- */
  function cta(b){
    var C=D.finalCta;
    return '<section class="final" id="contact">'+
      '<div class="bg">'+pic(b.image||C.image,'','loading="lazy" decoding="async"')+'</div>'+
      '<div class="scrim" aria-hidden="true"></div>'+
      '<div class="wrap rv"><p class="eyebrow on-dark fade">'+esc(b.eyebrow||C.eyebrow)+'</p>'+
      '<h2>'+headline([b.headline||C.headline])+'</h2>'+
      '<div class="final-actions">'+ctas(b.ctas||[C.primaryCta,C.secondaryCta])+'</div></div></section>';
  }

  function head(b,dark){
    if(!b.headline && !b.eyebrow) return '';
    return '<div class="sec-head rv"><div class="titles">'+
      (b.eyebrow?'<p class="eyebrow'+(dark?' on-dark':'')+' fade">'+esc(b.eyebrow)+'</p>':'')+
      (b.headline?'<h2>'+headline(b.headline)+'</h2>':'')+'</div>'+
      '<div class="aside'+(b.asideRight?' right':'')+'">'+
        (b.body?'<p class="lede'+(dark?' on-dark':'')+' fade">'+esc(b.body)+'</p>':'')+
        (b.cta?btn(b.cta, dark?'btn--ghost':'btn--outline'):'')+'</div></div>';
  }

  var RENDER={pagehero:pagehero,editorial:editorial,split:split,cards:cards,steps:steps,
              facts:facts,clips:clips,visibility:visibility,cta:cta,rooms:rooms};

  (page.blocks||[]).forEach(function(b){
    var fn=RENDER[b.type];
    if(fn) out.push(fn(b));
  });

  var main=document.querySelector('main');
  if(main) main.innerHTML=out.join('');

  /* page-level metadata */
  if(page.title) document.title=page.title;
  var md=document.querySelector('meta[name=description]');
  if(md&&page.description) md.setAttribute('content',page.description);

  U.start();
});
