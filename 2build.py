#!/usr/bin/env python3
"""
Build a Hugo video site from a JSON file.

    python 2build.py "videos - Copy.json" --out site --base-url https://example.com/ --build

Features
  * Fuse.js search over title / tags / description, index shipped gzipped
  * 36 videos per page on the homepage (Hugo pagination), 2 columns -> 4 columns
  * Video page: swipe up = next, swipe down = previous (also wheel / arrow keys)
  * SEO per video: title, description, canonical, Open Graph, Twitter, JSON-LD
    VideoObject + BreadcrumbList, video sitemap, robots.txt
Requires Hugo >= 0.128 (uses [pagination] pagerSize).
"""
import argparse, gzip, json, re, shutil, subprocess, sys, unicodedata, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

FUSE_CDN = "https://cdn.jsdelivr.net/npm/fuse.js@7.0.0/dist/fuse.min.js"

# --------------------------------------------------------------------------- helpers
def slugify(text, limit=60):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:limit].strip("-")

def oid_date(oid):  # Mongo ObjectId: first 4 bytes = unix timestamp
    try:
        return datetime.fromtimestamp(int(oid[:8], 16), timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)

def fmt_dur(s):
    h, r = divmod(int(s), 3600); m, sec = divmod(r, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

def iso_dur(s):
    h, r = divmod(int(s), 3600); m, sec = divmod(r, 60)
    return "PT" + (f"{h}H" if h else "") + (f"{m}M" if m else "") + f"{sec}S"

def q(v):  # JSON string == valid YAML/TOML string
    return json.dumps(v, ensure_ascii=False)

def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")

# --------------------------------------------------------------------------- content
def build_content(videos, out, page_size):
    videos = sorted(videos, key=lambda v: (oid_date(v["id"]), v["id"]), reverse=True)
    seen, slugs = set(), []
    for v in videos:
        s = f"{slugify(v.get('title', '')) or 'video'}-{v['id'][-6:]}"
        if s in seen:
            s = f"{s}-{v['id']}"
        seen.add(s); slugs.append(s)

    cdir = out / "content" / "videos"
    if cdir.exists():
        shutil.rmtree(cdir)
    write(cdir / "_index.md", '---\ntitle: "All videos"\n---\n')

    index = []
    for i, (v, slug) in enumerate(zip(videos, slugs)):
        title = (v.get("title") or "Untitled").strip()
        raw_desc = (v.get("description") or "").strip()
        tags = [t.strip() for t in v.get("tags", []) if t.strip()]
        dur = int(v.get("durationSeconds") or 0)
        has_desc = bool(raw_desc) and raw_desc.lower() != title.lower()
        meta_desc = raw_desc if has_desc else (
            f"Watch {title}" + (f" - {', '.join(tags[:5])}" if tags else "") +
            (f". Duration {fmt_dur(dur)}." if dur else "."))
        fm = {
            "title": title,
            "description": meta_desc,
            "has_desc": has_desc,
            "date": oid_date(v["id"]).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tags": tags,
            "video_url": v.get("videoUrl", ""),
            "thumbnail": v.get("thumbnailUrl", ""),
            "duration_seconds": dur,
            "duration": fmt_dur(dur),
            "duration_iso": iso_dur(dur),
            "views": int(v.get("views") or 0),
            "next_slug": slugs[i + 1] if i + 1 < len(slugs) else "",  # older
            "prev_slug": slugs[i - 1] if i > 0 else "",               # newer
            "slug": slug,
        }
        write(cdir / f"{slug}.md",
              "---\n" + "\n".join(f"{k}: {q(val)}" for k, val in fm.items()) + "\n---\n")
        index.append({"t": title, "d": raw_desc if has_desc else "", "g": tags,
                      "u": f"videos/{slug}/", "i": fm["thumbnail"],
                      "l": fm["duration"], "v": fm["views"]})
    return index

def write_search_index(index, out):
    data = json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode()
    write(out / "static" / "search-index.json", data.decode())          # fallback
    (out / "static" / "search-index.json.gz").write_bytes(gzip.compress(data, 9, mtime=0))
    print(f"search index: {len(data)/1024:.0f} KB -> "
          f"{len(gzip.compress(data, 9))/1024:.0f} KB gzipped")

# --------------------------------------------------------------------------- templates
CONFIG = """baseURL = {base}
title = {title}
languageCode = "en-US"
enableRobotsTXT = true
buildFuture = true
disableKinds = ["RSS"]

[pagination]
  pagerSize = {size}

[taxonomies]
  tag = "tags"

[sitemap]
  changeFreq = "weekly"
  priority = 0.5

[params]
  tagline = {tagline}
  description = {desc}
  adult = true            # adds rating=adult / RTA meta tags; set false if not adult content
  media_origin = {origin}
  fuse_src = {fuse}
"""

T = {}

T["layouts/_default/baseof.html"] = r"""<!doctype html>
<html lang="{{ site.Language.LanguageCode }}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
{{ block "seo" . }}{{ partial "seo.html" (dict "page" . "canon" .Permalink) }}{{ end }}
<link rel="stylesheet" href="{{ "css/site.css" | relURL }}">
{{ block "head" . }}{{ end }}
</head>
{{ $f := site.Params.fuse_src }}
<body class="{{ block "bodyclass" . }}{{ end }}" data-root="{{ "" | relURL }}" data-fuse="{{ if hasPrefix $f "http" }}{{ $f }}{{ else }}{{ $f | relURL }}{{ end }}">
{{ partial "header.html" . }}
{{ block "main" . }}{{ end }}
</body>
</html>
"""

T["layouts/partials/header.html"] = r"""<header class="top no-swipe">
  <a class="brand" href="{{ "" | relURL }}">{{ site.Title }}</a>
  <form class="search" action="{{ "" | relURL }}" method="get" role="search">
    <input id="q" type="search" name="q" placeholder="Search title, tags, description…" autocomplete="off" aria-label="Search videos">
  </form>
</header>
"""

T["layouts/partials/pg.html"] = r"""{{- $src := .Pages -}}
{{- if .IsHome }}{{ $src = where site.RegularPages "Section" "videos" }}{{ end -}}
{{- return (.Paginate $src) -}}
"""

T["layouts/partials/seo-list.html"] = r"""{{ if eq .Kind "taxonomy" }}
{{ partial "seo.html" (dict "page" . "canon" .Permalink) }}
{{ else }}
{{ $pg := partial "pg.html" . }}
{{ $suffix := "" }}{{ if gt $pg.PageNumber 1 }}{{ $suffix = printf " – Page %d" $pg.PageNumber }}{{ end }}
{{ $prev := "" }}{{ if $pg.HasPrev }}{{ $prev = $pg.Prev.URL | absURL }}{{ end }}
{{ $next := "" }}{{ if $pg.HasNext }}{{ $next = $pg.Next.URL | absURL }}{{ end }}
{{ partial "seo.html" (dict "page" . "canon" ($pg.URL | absURL) "suffix" $suffix "prev" $prev "next" $next) }}
{{ end }}
"""

T["layouts/partials/seo.html"] = r"""{{- $page := .page -}}{{- $canon := .canon -}}
{{- $isVideo := and $page.IsPage (eq $page.Type "videos") -}}
{{- $site := site.Title -}}
{{- $title := printf "%s | %s" $page.Title $site -}}
{{- $desc := site.Params.description -}}
{{- if $page.IsHome }}{{ $title = printf "%s – %s" $site site.Params.tagline }}
{{- else if eq $page.Kind "term" }}{{ $title = printf "%s videos | %s" $page.Title $site }}{{ $desc = printf "Watch %s videos on %s." $page.Title $site }}
{{- else if $isVideo }}{{ $desc = $page.Description }}
{{- end -}}
<title>{{ $title }}{{ .suffix }}</title>
<meta name="description" content="{{ $desc | truncate 160 }}">
<link rel="canonical" href="{{ $canon }}">
<meta name="robots" content="index,follow,max-image-preview:large,max-video-preview:-1,max-snippet:-1">
{{ if site.Params.adult }}<meta name="rating" content="adult">
<meta name="RATING" content="RTA-5042-1996-1400-1577-RTA">{{ end }}
{{ with .prev }}<link rel="prev" href="{{ . }}">{{ end }}
{{ with .next }}<link rel="next" href="{{ . }}">{{ end }}
<link rel="preconnect" href="{{ site.Params.media_origin }}" crossorigin>
<meta property="og:site_name" content="{{ $site }}">
<meta property="og:title" content="{{ $title }}">
<meta property="og:description" content="{{ $desc | truncate 200 }}">
<meta property="og:url" content="{{ $canon }}">
<meta name="twitter:title" content="{{ $title }}">
<meta name="twitter:description" content="{{ $desc | truncate 200 }}">
{{ if $isVideo }}
<meta property="og:type" content="video.other">
<meta property="og:image" content="{{ $page.Params.thumbnail }}">
<meta property="og:video" content="{{ $page.Params.video_url }}">
<meta property="og:video:secure_url" content="{{ $page.Params.video_url }}">
<meta property="og:video:type" content="video/mp4">
<meta property="video:duration" content="{{ $page.Params.duration_seconds }}">
<meta property="video:release_date" content="{{ $page.Date.Format "2006-01-02T15:04:05Z07:00" }}">
{{ range $page.Params.tags }}<meta property="video:tag" content="{{ . }}">
{{ end }}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{{ $page.Params.thumbnail }}">
{{ $ld := dict "@context" "https://schema.org" "@type" "VideoObject"
  "name" $page.Title "description" $page.Description
  "thumbnailUrl" (slice $page.Params.thumbnail)
  "uploadDate" ($page.Date.Format "2006-01-02T15:04:05Z07:00")
  "duration" $page.Params.duration_iso "contentUrl" $page.Params.video_url
  "url" $canon "keywords" (delimit $page.Params.tags ", ")
  "isFamilyFriendly" false
  "interactionStatistic" (dict "@type" "InteractionCounter" "interactionType" (dict "@type" "WatchAction") "userInteractionCount" $page.Params.views) }}
<script type="application/ld+json">{{ $ld | jsonify | safeJS }}</script>
{{ $bc := dict "@context" "https://schema.org" "@type" "BreadcrumbList" "itemListElement" (slice
  (dict "@type" "ListItem" "position" 1 "name" $site "item" ("" | absURL))
  (dict "@type" "ListItem" "position" 2 "name" $page.Title "item" $canon)) }}
<script type="application/ld+json">{{ $bc | jsonify | safeJS }}</script>
{{ else }}
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary">
{{ if $page.IsHome }}
{{ $ws := dict "@context" "https://schema.org" "@type" "WebSite" "name" $site "url" ("" | absURL)
  "potentialAction" (dict "@type" "SearchAction" "target" (printf "%s?q={search_term_string}" ("" | absURL)) "query-input" "required name=search_term_string") }}
<script type="application/ld+json">{{ $ws | jsonify | safeJS }}</script>
{{ end }}
{{ end }}
"""

T["layouts/partials/card.html"] = r"""{{ $p := .p }}<a class="card" href="{{ $p.RelPermalink }}">
<span class="thumb"><img src="{{ $p.Params.thumbnail }}" alt="{{ $p.Title }}" {{ if .eager }}fetchpriority="high"{{ else }}loading="lazy"{{ end }} decoding="async"><b class="dur">{{ $p.Params.duration }}</b></span>
<span class="t">{{ $p.Title }}</span>
<span class="m">{{ lang.FormatNumber 0 $p.Params.views }} views</span>
</a>
"""

T["layouts/partials/pager.html"] = r"""{{ $pg := . }}{{ if gt $pg.TotalPages 1 }}{{ $cur := $pg.PageNumber }}
<nav class="pager" id="pager" aria-label="Pagination">
{{ if $pg.HasPrev }}<a rel="prev" href="{{ $pg.Prev.URL }}" aria-label="Previous page">‹</a>{{ end }}
{{ range $pg.Pagers }}{{ $n := .PageNumber }}
{{ if or (eq $n 1) (eq $n $pg.TotalPages) (and (ge $n (sub $cur 2)) (le $n (add $cur 2))) }}
{{ if eq $n $cur }}<span class="cur" aria-current="page">{{ $n }}</span>{{ else }}<a href="{{ .URL }}">{{ $n }}</a>{{ end }}
{{ else if or (eq $n (sub $cur 3)) (eq $n (add $cur 3)) }}<span class="gap">…</span>{{ end }}
{{ end }}
{{ if $pg.HasNext }}<a rel="next" href="{{ $pg.Next.URL }}" aria-label="Next page">›</a>{{ end }}
</nav>{{ end }}
"""

T["layouts/index.html"] = r"""{{ define "seo" }}{{ partial "seo-list.html" . }}{{ end }}
{{ define "main" }}
{{ $pg := partial "pg.html" . }}
<main class="wrap">
  <h1 class="sr">{{ site.Title }}</h1>
  <p id="status" class="status" role="status" hidden></p>
  <div class="grid" id="grid">{{ range $i, $p := $pg.Pages }}{{ partial "card.html" (dict "p" $p "eager" (lt $i 4)) }}{{ end }}</div>
  <button id="more" class="more" type="button" hidden>Load more</button>
  {{ partial "pager.html" $pg }}
</main>
<script src="{{ "js/search.js" | relURL }}" defer></script>
{{ end }}
"""

T["layouts/_default/list.html"] = r"""{{ define "seo" }}{{ partial "seo-list.html" . }}{{ end }}
{{ define "main" }}
<main class="wrap">
{{ if eq .Kind "taxonomy" }}
  <h1>All tags</h1>
  <ul class="tagcloud">{{ range .Data.Terms.Alphabetical }}<li><a href="{{ .Page.RelPermalink }}">{{ .Page.Title }} <small>{{ .Count }}</small></a></li>{{ end }}</ul>
{{ else }}
  {{ $pg := partial "pg.html" . }}
  <h1>{{ if eq .Kind "term" }}{{ .Title }} videos{{ else }}{{ .Title }}{{ end }}</h1>
  <div class="grid">{{ range $i, $p := $pg.Pages }}{{ partial "card.html" (dict "p" $p "eager" (lt $i 4)) }}{{ end }}</div>
  {{ partial "pager.html" $pg }}
{{ end }}
</main>
{{ end }}
"""

T["layouts/videos/single.html"] = r"""{{ define "bodyclass" }}vp{{ end }}
{{ define "head" }}
{{ with .Params.next_slug }}<link rel="prefetch" href="{{ printf "videos/%s/" . | relURL }}">{{ end }}
{{ with .Params.prev_slug }}<link rel="prefetch" href="{{ printf "videos/%s/" . | relURL }}">{{ end }}
{{ end }}
{{ define "main" }}
<main class="player" data-next="{{ with .Params.next_slug }}{{ printf "videos/%s/" . | relURL }}{{ end }}" data-prev="{{ with .Params.prev_slug }}{{ printf "videos/%s/" . | relURL }}{{ end }}">
  <video src="{{ .Params.video_url }}" poster="{{ .Params.thumbnail }}" autoplay muted loop playsinline preload="metadata"></video>
  <article class="info">
    <h1>{{ .Title }}</h1>
    {{ if .Params.has_desc }}<p>{{ .Description }}</p>{{ end }}
    <ul class="tags no-swipe">{{ range .GetTerms "tags" }}<li><a href="{{ .RelPermalink }}">#{{ .LinkTitle }}</a></li>{{ end }}</ul>
    <small>{{ lang.FormatNumber 0 .Params.views }} views · {{ .Params.duration }}</small>
  </article>
  <div class="side no-swipe">
    <button id="up" type="button" aria-label="Previous video">▲</button>
    <button id="down" type="button" aria-label="Next video">▼</button>
    <button id="mute" type="button" aria-label="Toggle sound">🔇</button>
  </div>
  <div class="bar no-swipe" id="bar"><i></i></div>
</main>
<script src="{{ "js/swipe.js" | relURL }}" defer></script>
{{ end }}
"""

T["layouts/_default/sitemap.xml"] = r"""{{ printf "<?xml version=\"1.0\" encoding=\"utf-8\" standalone=\"yes\"?>" | safeHTML }}
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:video="http://www.google.com/schemas/sitemap-video/1.1">
{{ range .Data.Pages }}{{ if .Permalink }}
<url><loc>{{ .Permalink }}</loc>{{ if not .Lastmod.IsZero }}<lastmod>{{ .Lastmod.Format "2006-01-02T15:04:05Z07:00" }}</lastmod>{{ end }}
{{ if and .IsPage (eq .Type "videos") }}<video:video>
<video:thumbnail_loc>{{ .Params.thumbnail }}</video:thumbnail_loc>
<video:title>{{ .Title | truncate 100 }}</video:title>
<video:description>{{ .Description | truncate 2000 }}</video:description>
<video:content_loc>{{ .Params.video_url }}</video:content_loc>
<video:duration>{{ .Params.duration_seconds }}</video:duration>
<video:view_count>{{ .Params.views }}</video:view_count>
<video:publication_date>{{ .Date.Format "2006-01-02T15:04:05Z07:00" }}</video:publication_date>
<video:family_friendly>no</video:family_friendly>
{{ range first 32 .Params.tags }}<video:tag>{{ . }}</video:tag>
{{ end }}</video:video>{{ end }}
</url>{{ end }}{{ end }}
</urlset>
"""

T["layouts/robots.txt"] = """User-agent: *
Allow: /

Sitemap: {{ "sitemap.xml" | absURL }}
"""

T["static/css/site.css"] = r""":root{--bg:#0e0f12;--panel:#181a20;--fg:#ecebe8;--dim:#9a9aa3;--acc:#ff5a7a;color-scheme:dark}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:inherit;text-decoration:none}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.top{position:sticky;top:0;z-index:20;display:flex;gap:12px;align-items:center;padding:10px 12px;background:rgba(14,15,18,.92);backdrop-filter:blur(8px)}
.brand{font-weight:700;letter-spacing:-.02em;white-space:nowrap}
.search{flex:1;margin:0}
.search input{width:100%;padding:9px 14px;border-radius:999px;border:1px solid #2a2c35;background:var(--panel);color:var(--fg);font:inherit}
.wrap{max-width:1400px;margin:0 auto;padding:8px 12px 40px}
.wrap h1{font-size:20px;margin:10px 2px 14px}
.wrap h1.sr{margin:0}
/* 2 columns on phones -> 4 columns from 768px */
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 8px}
@media(min-width:768px){.grid{grid-template-columns:repeat(4,minmax(0,1fr));gap:20px 14px}}
.card{display:block;min-width:0}
.thumb{display:block;position:relative;aspect-ratio:16/9;background:var(--panel);border-radius:8px;overflow:hidden}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.dur{position:absolute;right:6px;bottom:6px;background:rgba(0,0,0,.78);padding:1px 6px;border-radius:4px;font-size:12px;font-weight:600}
.t{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;margin-top:6px;font-weight:600;font-size:14px;line-height:1.3}
.m{display:block;color:var(--dim);font-size:12px;margin-top:2px}
.status{color:var(--dim);margin:10px 2px}
.more{display:block;margin:26px auto;padding:10px 30px;border:0;border-radius:999px;background:var(--acc);color:#fff;font:inherit;font-weight:600;cursor:pointer}
.pager{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;margin:30px 0}
.pager a,.pager span{min-width:38px;padding:8px 10px;text-align:center;border-radius:8px;background:var(--panel)}
.pager .cur{background:var(--acc);color:#fff;font-weight:700}
.pager .gap{background:none}
.tagcloud{display:flex;flex-wrap:wrap;gap:8px;list-style:none;padding:0}
.tagcloud a{display:block;padding:6px 12px;border-radius:999px;background:var(--panel)}
.tagcloud small{color:var(--dim)}
/* video page */
body.vp{height:100dvh;overflow:hidden;overscroll-behavior:none}
body.vp .top{position:fixed;left:0;right:0;background:linear-gradient(rgba(0,0,0,.75),transparent);backdrop-filter:none}
.player{position:fixed;inset:0;background:#000;touch-action:none;user-select:none;-webkit-user-select:none;transition:transform .16s ease-in,opacity .16s}
.player.out-up{transform:translateY(-100%);opacity:.4}
.player.out-down{transform:translateY(100%);opacity:.4}
.player video{width:100%;height:100%;object-fit:contain;display:block}
.player.paused::after{content:"▶";position:absolute;inset:0;display:grid;place-items:center;font-size:64px;color:rgba(255,255,255,.6);pointer-events:none}
.info{position:absolute;left:0;right:64px;bottom:0;padding:40px 14px calc(26px + env(safe-area-inset-bottom));background:linear-gradient(transparent,rgba(0,0,0,.88));pointer-events:none}
.info a{pointer-events:auto}
.info h1{font-size:18px;margin:0 0 4px}
.info p{margin:0 0 4px;color:#d6d4d0}
.info small{color:var(--dim)}
.tags{display:flex;flex-wrap:wrap;gap:6px;list-style:none;padding:0;margin:8px 0}
.tags a{display:block;padding:3px 10px;background:rgba(255,255,255,.15);border-radius:999px;font-size:13px}
.side{position:absolute;right:8px;bottom:calc(60px + env(safe-area-inset-bottom));display:flex;flex-direction:column;gap:10px}
.side button{width:44px;height:44px;border:0;border-radius:50%;background:rgba(255,255,255,.16);color:#fff;font-size:16px;cursor:pointer}
.bar{position:absolute;left:0;right:0;bottom:0;height:18px;cursor:pointer}
.bar i{display:block;height:3px;margin-top:15px;width:0;background:var(--acc)}
"""

T["static/js/search.js"] = r"""(() => {
  const $ = s => document.querySelector(s);
  const root = document.body.dataset.root, fuseSrc = document.body.dataset.fuse;
  const grid = $('#grid'), more = $('#more'), pager = $('#pager'), status = $('#status'), input = $('#q');
  const BATCH = 36, original = grid.innerHTML;
  let fuse, loading, hits = [], shown = 0, seq = 0, timer;

  const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const card = v => `<a class="card" href="${root}${esc(v.u)}"><span class="thumb"><img src="${esc(v.i)}" alt="${esc(v.t)}" loading="lazy" decoding="async"><b class="dur">${esc(v.l)}</b></span><span class="t">${esc(v.t)}</span><span class="m">${(v.v || 0).toLocaleString()} views</span></a>`;

  const loadFuse = () => new Promise((ok, fail) => {
    if (window.Fuse) return ok();
    const s = document.createElement('script');
    s.src = fuseSrc; s.onload = ok; s.onerror = fail; document.head.appendChild(s);
  });

  async function readIndex() {
    try {   // gzipped index, decompressed in the browser
      const buf = await (await fetch(root + 'search-index.json.gz')).arrayBuffer();
      const b = new Uint8Array(buf);
      if (b[0] === 0x1f && b[1] === 0x8b) {  // server did not already decode it
        const stream = new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'));
        return JSON.parse(await new Response(stream).text());
      }
      return JSON.parse(new TextDecoder().decode(b));
    } catch (e) {   // old browser without DecompressionStream
      return (await fetch(root + 'search-index.json')).json();
    }
  }

  const init = () => loading || (loading = Promise.all([loadFuse(), readIndex()]).then(([, data]) => {
    fuse = new Fuse(data, {
      keys: [{name: 't', weight: .5}, {name: 'g', weight: .3}, {name: 'd', weight: .2}],
      threshold: .3, ignoreLocation: true, minMatchCharLength: 2
    });
  }));

  function renderMore() {
    const slice = hits.slice(shown, shown + BATCH);
    grid.insertAdjacentHTML('beforeend', slice.map(card).join(''));
    shown += slice.length;
    more.hidden = shown >= hits.length;
  }

  async function run(term, push) {
    const my = ++seq;
    term = term.trim();
    if (push) history.replaceState(null, '', term ? `?q=${encodeURIComponent(term)}` : location.pathname);
    if (!term) {
      grid.innerHTML = original; more.hidden = true; status.hidden = true;
      if (pager) pager.hidden = false;
      return;
    }
    status.hidden = false; status.textContent = 'Searching…';
    await init();
    if (my !== seq) return;               // a newer query superseded this one
    hits = fuse.search(term).map(r => r.item);
    shown = 0; grid.innerHTML = '';
    if (pager) pager.hidden = true;
    status.textContent = hits.length ? `${hits.length.toLocaleString()} results for “${term}”` : `No results for “${term}”`;
    renderMore();
  }

  input.addEventListener('focus', init, {once: true});   // warm up while the user types
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => run(input.value, true), 180); });
  input.closest('form').addEventListener('submit', e => { e.preventDefault(); clearTimeout(timer); run(input.value, true); });
  more.addEventListener('click', renderMore);

  const initial = new URLSearchParams(location.search).get('q');
  if (initial) { input.value = initial; run(initial, false); }
})();
"""

T["static/js/swipe.js"] = r"""(() => {
  const p = document.querySelector('.player'), v = p.querySelector('video');
  const { next, prev } = p.dataset;
  const mute = document.getElementById('mute'), bar = document.getElementById('bar');
  let leaving = false;

  function go(url, dir) {
    if (!url || leaving) return;
    leaving = true;
    p.classList.add(dir > 0 ? 'out-up' : 'out-down');
    setTimeout(() => { location.href = url; }, 160);
  }
  const goNext = () => go(next, 1), goPrev = () => go(prev, -1);
  addEventListener('pageshow', () => { leaving = false; p.classList.remove('out-up', 'out-down'); });

  // touch: swipe up -> next video, swipe down -> previous video
  let sx, sy, st, track = false;
  p.addEventListener('touchstart', e => {
    track = e.touches.length === 1 && !e.target.closest('.no-swipe');
    if (track) { sx = e.touches[0].clientX; sy = e.touches[0].clientY; st = Date.now(); }
  }, { passive: true });
  p.addEventListener('touchend', e => {
    if (!track) return; track = false;
    const t = e.changedTouches[0], dx = t.clientX - sx, dy = t.clientY - sy;
    if (Math.abs(dy) > 60 && Math.abs(dy) > Math.abs(dx) * 1.5 && Date.now() - st < 900) {
      dy < 0 ? goNext() : goPrev();
    }
  }, { passive: true });

  // desktop: mouse wheel and keyboard
  let wl = 0;
  addEventListener('wheel', e => {
    if (Math.abs(e.deltaY) < 30 || Date.now() - wl < 800) return;
    wl = Date.now(); e.deltaY > 0 ? goNext() : goPrev();
  }, { passive: true });
  addEventListener('keydown', e => {
    if (e.target.matches('input')) return;
    if (e.key === 'ArrowDown' || e.key === 'j') goNext();
    else if (e.key === 'ArrowUp' || e.key === 'k') goPrev();
    else if (e.key === ' ') { e.preventDefault(); toggle(); }
    else if (e.key === 'm') setMuted(!v.muted);
  });
  document.getElementById('down').onclick = goNext;
  document.getElementById('up').onclick = goPrev;

  // playback
  const toggle = () => (v.paused ? v.play() : v.pause());
  p.addEventListener('click', e => { if (!e.target.closest('.no-swipe')) toggle(); });
  v.addEventListener('pause', () => p.classList.add('paused'));
  v.addEventListener('play', () => p.classList.remove('paused'));
  v.addEventListener('timeupdate', () => { bar.firstChild.style.width = (v.currentTime / (v.duration || 1) * 100) + '%'; });
  bar.addEventListener('click', e => { const r = bar.getBoundingClientRect(); v.currentTime = (e.clientX - r.left) / r.width * v.duration; });

  function setMuted(m) {
    v.muted = m; mute.textContent = m ? '🔇' : '🔊';
    try { sessionStorage.setItem('muted', m ? '1' : '0'); } catch (e) {}
  }
  mute.onclick = () => setMuted(!v.muted);
  let wantSound = false;
  try { wantSound = sessionStorage.getItem('muted') === '0'; } catch (e) {}
  if (wantSound) {   // keep sound on between videos if the browser allows it
    v.muted = false;
    v.play().then(() => setMuted(false)).catch(() => { v.muted = true; v.play(); });
  }
})();
"""

# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json_file")
    ap.add_argument("--out", default="site", help="Hugo project directory (default: site)")
    ap.add_argument("--base-url", default="https://example.com/")
    ap.add_argument("--title", default="VideoHub")
    ap.add_argument("--tagline", default="Watch the latest videos")
    ap.add_argument("--page-size", type=int, default=36)
    ap.add_argument("--vendor-fuse", action="store_true", help="download Fuse.js into static/js instead of using the CDN")
    ap.add_argument("--build", action="store_true", help="run `hugo --minify` afterwards")
    a = ap.parse_args()

    videos = json.loads(Path(a.json_file).read_text(encoding="utf-8-sig"))
    videos = [v for v in videos if v.get("id") and v.get("videoUrl")]
    out = Path(a.out)
    print(f"{len(videos)} videos")

    fuse_src = FUSE_CDN
    if a.vendor_fuse:
        dest = out / "static/js/fuse.min.js"; dest.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(FUSE_CDN, dest); fuse_src = "js/fuse.min.js"

    origin = "{0.scheme}://{0.netloc}".format(urlparse(videos[0].get("thumbnailUrl") or videos[0]["videoUrl"])) if videos else ""
    write(out / "hugo.toml", CONFIG.format(
        base=q(a.base_url.rstrip("/") + "/"), title=q(a.title), size=a.page_size,
        tagline=q(a.tagline), desc=q(f"{a.title}: {a.tagline}. Browse and search {len(videos)} videos by title, tag and description."),
        origin=q(origin), fuse=q(fuse_src)))
    for path, text in T.items():
        write(out / path, text)

    index = build_content(videos, out, a.page_size)
    write_search_index(index, out)

    if a.build:
        if not shutil.which("hugo"):
            sys.exit("hugo not found in PATH - install it from https://gohugo.io/installation/")
        subprocess.run(["hugo", "--minify", "-s", str(out)], check=True)
        print(f"built -> {out/'public'}")
    else:
        print(f"\nnext:  cd {out} && hugo server      (or: hugo --minify)")

if __name__ == "__main__":
    main()