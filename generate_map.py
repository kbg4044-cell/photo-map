import os, json, struct
from pathlib import Path

PHOTOS_DIR  = Path("photos")
OUTPUT_HTML = Path("index.html")

def extract_gps(filepath):
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
        i = 2
        while i < len(data) - 1:
            if data[i] != 0xFF:
                break
            marker = data[i+1]
            length = struct.unpack('>H', data[i+2:i+4])[0]
            if marker == 0xE1:
                seg = data[i+4:i+2+length]
                if seg[:4] == b'Exif':
                    return parse_gps(seg[6:])
            i += 2 + length
    except:
        pass
    return None

def parse_gps(tiff):
    try:
        bo = '<' if tiff[:2] == b'II' else '>'
        def r16(o): return struct.unpack_from(bo+'H', tiff, o)[0]
        def r32(o): return struct.unpack_from(bo+'I', tiff, o)[0]
        def rat(o):
            n = r32(o); d = r32(o+4)
            return n/d if d else 0
        ifd0 = r32(4)
        gps_off = None
        for i in range(r16(ifd0)):
            base = ifd0 + 2 + i*12
            if r16(base) == 0x8825:
                gps_off = r32(base+8)
                break
        if not gps_off:
            return None
        gps = {}
        for i in range(r16(gps_off)):
            base = gps_off + 2 + i*12
            tag = r16(base)
            typ = r16(base+2)
            cnt = r32(base+4)
            vo  = base+8
            if typ == 5:
                off = r32(vo)
                gps[tag] = [rat(off + j*8) for j in range(cnt)]
            elif typ == 2:
                off = r32(vo) if cnt > 4 else vo
                gps[tag] = tiff[off:off+cnt].rstrip(b'\x00').decode('ascii', errors='ignore')
        if 2 not in gps or 4 not in gps:
            return None
        def deg(v): return v[0] + v[1]/60 + v[2]/3600
        lat = deg(gps[2]); lon = deg(gps[4])
        if gps.get(1) == 'S': lat = -lat
        if gps.get(3) == 'W': lon = -lon
        return round(lat,6), round(lon,6)
    except:
        return None

def get_date(filepath):
    try:
        with open(filepath, 'rb') as f:
            data = f.read(65536)
        idx = data.find(b'DateTimeOriginal\x00')
        if idx > 0:
            raw = data[idx+17:idx+37]
            s = raw.split(b'\x00')[0].decode('ascii', errors='ignore')
            if len(s) >= 10:
                return s[:10].replace(':', '-')
    except:
        pass
    return ''

def cluster_photos(photos, threshold=0.0005):
    """가까운 사진들을 하나의 클러스터로 묶기 (약 50m 이내)"""
    clusters = []
    used = set()
    for i, p in enumerate(photos):
        if i in used:
            continue
        cluster = [p]
        used.add(i)
        for j, q in enumerate(photos):
            if j in used:
                continue
            if abs(p['lat']-q['lat']) < threshold and abs(p['lng']-q['lng']) < threshold:
                cluster.append(q)
                used.add(j)
        clusters.append(cluster)
    return clusters

def main():
    photos_data = []
    exts = {'.jpg', '.jpeg', '.JPG', '.JPEG'}
    for f in sorted(PHOTOS_DIR.iterdir()):
        if f.suffix not in exts or f.name.startswith('.'):
            continue
        gps = extract_gps(f)
        if gps:
            lat, lon = gps
            photos_data.append({
                "name": f.name,
                "lat":  lat,
                "lng":  lon,
                "url":  f"photos/{f.name}",
                "date": get_date(f)
            })
            print(f"  ✅ {f.name} → {lat}, {lon}")
        else:
            print(f"  ⚠️  {f.name} → GPS 없음, 스킵")

    clusters = cluster_photos(photos_data)
    clusters_json = json.dumps(clusters, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>나의 포토맵</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family:'Malgun Gothic',sans-serif; background:#0f0f1a; color:#fff; height:100vh; display:flex; flex-direction:column; }}
    header {{ padding:12px 20px; background:rgba(255,255,255,.06); border-bottom:1px solid rgba(255,255,255,.1); display:flex; align-items:center; justify-content:space-between; flex-shrink:0; }}
    header h1 {{ font-size:1.1rem; font-weight:500; }}
    .badge {{ background:rgba(29,158,117,.25); border:1px solid #1D9E75; color:#5DCAA5; padding:3px 12px; border-radius:20px; font-size:.8rem; }}
    #map {{ flex:1; }}

    /* 클러스터 마커 */
    .cluster-marker {{
      background:#1D9E75; color:#fff; border:2.5px solid #fff;
      border-radius:50%; display:flex; align-items:center; justify-content:center;
      font-size:12px; font-weight:500; box-shadow:0 2px 6px rgba(0,0,0,.4);
    }}

    /* 팝업 슬라이더 */
    .popup-wrap {{ width:240px; }}
    .slider-box {{ position:relative; overflow:hidden; border-radius:8px; background:#111; }}
    .slider-box img {{ width:100%; height:160px; object-fit:cover; display:block; cursor:zoom-in; }}
    .slide {{ display:none; }}
    .slide.active {{ display:block; }}
    .nav {{ display:flex; align-items:center; justify-content:space-between; padding:6px 4px 2px; }}
    .nav button {{ background:rgba(255,255,255,.1); border:none; color:#fff; border-radius:6px; padding:3px 10px; cursor:pointer; font-size:14px; }}
    .nav button:hover {{ background:rgba(255,255,255,.25); }}
    .nav .counter {{ font-size:12px; color:#aaa; }}
    .pname {{ font-size:.8rem; font-weight:500; color:#222; margin:6px 0 2px; word-break:break-all; }}
    .pdate {{ font-size:.75rem; color:#1D9E75; }}
    .pcoord {{ font-size:.72rem; color:#888; margin-top:2px; }}

    /* 라이트박스 */
    #lb {{ display:none; position:absolute; inset:0; background:rgba(0,0,0,.9); z-index:9999; flex-direction:column; align-items:center; justify-content:center; gap:14px; }}
    #lb.on {{ display:flex; }}
    #lb img {{ max-width:92vw; max-height:78vh; border-radius:10px; }}
    #lb .meta {{ background:rgba(255,255,255,.12); padding:8px 20px; border-radius:20px; font-size:.85rem; text-align:center; }}
    #lb .cls {{ position:absolute; top:16px; right:20px; font-size:1.6rem; cursor:pointer; opacity:.7; }}
    #lb .cls:hover {{ opacity:1; }}
    #lb .lb-nav {{ display:flex; gap:20px; }}
    #lb .lb-nav button {{ background:rgba(255,255,255,.15); border:none; color:#fff; padding:8px 20px; border-radius:20px; cursor:pointer; font-size:1rem; }}
    #lb .lb-nav button:hover {{ background:rgba(255,255,255,.3); }}
  </style>
</head>
<body>
<header>
  <h1>📸 나의 포토맵</h1>
  <span class="badge" id="cnt">불러오는 중...</span>
</header>
<div id="map"></div>
<div id="lb">
  <span class="cls" onclick="closeLb()">✕</span>
  <img id="lb-img" src="" alt="">
  <div class="meta" id="lb-meta"></div>
  <div class="lb-nav">
    <button onclick="lbMove(-1)">◀ 이전</button>
    <button onclick="lbMove(1)">다음 ▶</button>
  </div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const clusters = {clusters_json};
const totalPhotos = clusters.reduce((s,c) => s+c.length, 0);

let lbPhotos = [], lbIdx = 0;

function openLb(photos, idx) {{
  lbPhotos = photos; lbIdx = idx;
  updateLb();
  document.getElementById('lb').classList.add('on');
}}
function updateLb() {{
  const p = lbPhotos[lbIdx];
  document.getElementById('lb-img').src = p.url;
  document.getElementById('lb-meta').textContent =
    p.name + (p.date ? '  ·  ' + p.date : '') + '  (' + (lbIdx+1) + '/' + lbPhotos.length + ')';
}}
function lbMove(dir) {{
  lbIdx = (lbIdx + dir + lbPhotos.length) % lbPhotos.length;
  updateLb();
}}
function closeLb() {{ document.getElementById('lb').classList.remove('on'); }}
document.getElementById('lb').addEventListener('click', e => {{ if(e.target.id==='lb') closeLb(); }});
document.addEventListener('keydown', e => {{
  if(e.key==='Escape') closeLb();
  if(e.key==='ArrowLeft') lbMove(-1);
  if(e.key==='ArrowRight') lbMove(1);
}});

if (!clusters.length) {{
  document.getElementById('cnt').textContent = '사진 없음';
  document.getElementById('map').innerHTML =
    '<p style="text-align:center;padding:80px;color:#555">photos/ 폴더에 GPS 사진을 올려보세요!</p>';
}} else {{
  document.getElementById('cnt').textContent = '📍 ' + totalPhotos + '장 / ' + clusters.length + '곳';

  const map = L.map('map');
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19
  }}).addTo(map);

  const group = L.featureGroup();

  clusters.forEach(photos => {{
    const lat = photos.reduce((s,p)=>s+p.lat,0)/photos.length;
    const lng = photos.reduce((s,p)=>s+p.lng,0)/photos.length;
    const count = photos.length;
    const size = count > 1 ? 36 : 14;

    const icon = count > 1
      ? L.divIcon({{
          className: '',
          html: `<div class="cluster-marker" style="width:${{size}}px;height:${{size}}px">${{count}}</div>`,
          iconSize: [size, size], iconAnchor: [size/2, size/2]
        }})
      : L.divIcon({{
          className: '',
          html: '<div style="width:14px;height:14px;background:#1D9E75;border:2.5px solid #fff;border-radius:50%;box-shadow:0 1px 4px rgba(0,0,0,.4)"></div>',
          iconSize: [14,14], iconAnchor: [7,7]
        }});

    const marker = L.marker([lat, lng], {{icon}}).addTo(map);

    const sliderId = 'sl' + Math.random().toString(36).slice(2);
    const slides = photos.map((p,i) => `
      <div class="slide ${{i===0?'active':''}}" id="${{sliderId}}_${{i}}">
        <img src="${{p.url}}" onerror="this.style.display='none'"
             onclick="openLb(${{JSON.stringify(photos).replace(/'/g,'&#39;')}},${{i}})">
      </div>`).join('');

    const popupHtml = `
      <div class="popup-wrap">
        <div class="slider-box">${{slides}}</div>
        ${{photos.length > 1 ? `
        <div class="nav">
          <button onclick="slideMove('${{sliderId}}',-1,${{photos.length}})">◀</button>
          <span class="counter" id="${{sliderId}}_cnt">1 / ${{photos.length}}</span>
          <button onclick="slideMove('${{sliderId}}',1,${{photos.length}})">▶</button>
        </div>` : ''}}
        <div id="${{sliderId}}_info">
          <div class="pname">${{photos[0].name}}</div>
          <div class="pdate">${{photos[0].date || '날짜 없음'}}</div>
          <div class="pcoord">${{photos[0].lat}}, ${{photos[0].lng}}</div>
        </div>
      </div>`;

    marker.bindPopup(popupHtml, {{maxWidth:260}});
  }});

  function slideMove(id, dir, total) {{
    const slides = document.querySelectorAll(`[id^="${{id}}_"]:not([id$="_cnt"]):not([id$="_info"])`);
    let cur = 0;
    slides.forEach((s,i) => {{ if(s.classList.contains('active')) cur = i; }});
    slides[cur].classList.remove('active');
    cur = (cur + dir + total) % total;
    slides[cur].classList.add('active');
    const cnt = document.getElementById(id+'_cnt');
    if(cnt) cnt.textContent = (cur+1) + ' / ' + total;
  }}
  window.slideMove = slideMove;

  map.fitBounds(group.getBounds ? group.getBounds() : [[35,126],[38,130]], {{padding:[40,40]}});
  clusters.forEach(photos => {{
    const lat = photos.reduce((s,p)=>s+p.lat,0)/photos.length;
    const lng = photos.reduce((s,p)=>s+p.lng,0)/photos.length;
    group.addLayer(L.marker([lat,lng]));
  }});
  map.addLayer(group);
  if(clusters.length > 0) map.fitBounds(group.getBounds(), {{padding:[40,40]}});
}}
</script>
</body>
</html>"""

    OUTPUT_HTML.write_text(html, encoding='utf-8')
    print(f"\\n✅ index.html 생성 완료 — {len(photos_data)}장 / {len(clusters)}곳")

if __name__ == "__main__":
    main()
