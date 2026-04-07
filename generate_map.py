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

def cluster_photos(photos, threshold=0.001):
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
    total = len(photos_data)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>나의 포토맵</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    *{{margin:0;padding:0;box-sizing:border-box}}
    body{{font-family:'Malgun Gothic',sans-serif;background:#0f0f1a;color:#fff;height:100vh;display:flex;flex-direction:column}}
    header{{padding:12px 20px;background:rgba(255,255,255,.06);border-bottom:1px solid rgba(255,255,255,.1);display:flex;align-items:center;justify-content:space-between;flex-shrink:0}}
    header h1{{font-size:1.1rem;font-weight:500}}
    .badge{{background:rgba(29,158,117,.25);border:1px solid #1D9E75;color:#5DCAA5;padding:3px 12px;border-radius:20px;font-size:.8rem}}
    #map{{flex:1}}
    .cm{{background:#1D9E75;color:#fff;border:2.5px solid #fff;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:600;box-shadow:0 2px 8px rgba(0,0,0,.5);cursor:pointer}}
    .leaflet-popup-content{{margin:10px 12px}}
    .pw{{width:220px}}
    .ph-wrap{{position:relative;background:#000;border-radius:8px;overflow:hidden}}
    .ph-wrap img{{width:100%;height:155px;object-fit:cover;display:block;cursor:zoom-in}}
    .ph-nav{{display:flex;align-items:center;justify-content:space-between;padding:5px 2px}}
    .ph-btn{{background:#1D9E75;border:none;color:#fff;border-radius:6px;padding:3px 12px;cursor:pointer;font-size:15px;font-weight:600}}
    .ph-btn:hover{{background:#0F6E56}}
    .ph-cnt{{font-size:12px;color:#555;font-weight:500}}
    .pname{{font-size:.8rem;font-weight:600;color:#222;margin:4px 0 2px;word-break:break-all}}
    .pdate{{font-size:.75rem;color:#1D9E75}}
    .pcoord{{font-size:.72rem;color:#999;margin-top:1px}}
    #lb{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.92);z-index:99999;flex-direction:column;align-items:center;justify-content:center;gap:16px}}
    #lb.on{{display:flex}}
    #lb img{{max-width:92vw;max-height:76vh;border-radius:10px}}
    #lb .lmeta{{background:rgba(255,255,255,.12);padding:8px 20px;border-radius:20px;font-size:.85rem;text-align:center}}
    #lb .lcls{{position:absolute;top:16px;right:20px;font-size:1.8rem;cursor:pointer;opacity:.7;line-height:1}}
    #lb .lcls:hover{{opacity:1}}
    #lb .lnav{{display:flex;gap:16px}}
    #lb .lnav button{{background:rgba(255,255,255,.15);border:none;color:#fff;padding:8px 24px;border-radius:20px;cursor:pointer;font-size:1rem}}
    #lb .lnav button:hover{{background:rgba(255,255,255,.3)}}
  </style>
</head>
<body>
<header>
  <h1>📸 나의 포토맵</h1>
  <span class="badge" id="cnt">불러오는 중...</span>
</header>
<div id="map"></div>
<div id="lb">
  <span class="lcls" onclick="closeLb()">✕</span>
  <img id="lb-img" src="" alt="">
  <div class="lmeta" id="lb-meta"></div>
  <div class="lnav">
    <button onclick="lbMove(-1)">◀ 이전</button>
    <button onclick="lbMove(1)">다음 ▶</button>
  </div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const clusters = {clusters_json};
const total = {total};
let lbList=[], lbIdx=0;

function openLb(list, idx){{
  lbList=list; lbIdx=idx; updateLb();
  document.getElementById('lb').classList.add('on');
}}
function updateLb(){{
  const p=lbList[lbIdx];
  document.getElementById('lb-img').src=p.url;
  document.getElementById('lb-meta').textContent=
    p.name+(p.date?' · '+p.date:'')+' ('+( lbIdx+1)+'/'+lbList.length+')';
}}
function lbMove(d){{
  lbIdx=(lbIdx+d+lbList.length)%lbList.length;
  updateLb();
}}
function closeLb(){{document.getElementById('lb').classList.remove('on');}}
document.getElementById('lb').addEventListener('click',e=>{{if(e.target.id==='lb')closeLb();}});
document.addEventListener('keydown',e=>{{
  if(e.key==='Escape')closeLb();
  if(e.key==='ArrowLeft')lbMove(-1);
  if(e.key==='ArrowRight')lbMove(1);
}});

if(!clusters.length){{
  document.getElementById('cnt').textContent='사진 없음';
  document.getElementById('map').innerHTML='<p style="text-align:center;padding:80px;color:#555">photos/ 폴더에 GPS 사진을 올려보세요!</p>';
}}else{{
  document.getElementById('cnt').textContent='📍 '+total+'장 / '+clusters.length+'곳';
  const map=L.map('map');
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{
    attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom:19
  }}).addTo(map);

  const bounds=[];
  clusters.forEach((photos,ci)=>{{
    const lat=photos.reduce((s,p)=>s+p.lat,0)/photos.length;
    const lng=photos.reduce((s,p)=>s+p.lng,0)/photos.length;
    const n=photos.length;
    const sz=n>1?38:14;
    const icon=L.divIcon({{
      className:'',
      html:n>1
        ?`<div class="cm" style="width:${{sz}}px;height:${{sz}}px">${{n}}</div>`
        :`<div style="width:14px;height:14px;background:#1D9E75;border:2.5px solid #fff;border-radius:50%;box-shadow:0 1px 4px rgba(0,0,0,.5)"></div>`,
      iconSize:[sz,sz],iconAnchor:[sz/2,sz/2]
    }});

    const marker=L.marker([lat,lng],{{icon}}).addTo(map);
    bounds.push([lat,lng]);

    let cur=0;
    const pid='p'+ci;

    function buildPopup(idx){{
      const p=photos[idx];
      const photoList=JSON.stringify(photos);
      return `<div class="pw">
        <div class="ph-wrap">
          <img src="${{p.url}}" onerror="this.style.display='none'"
               onclick='openLb(${{photoList}},${{idx}})'>
        </div>
        ${{n>1?`<div class="ph-nav">
          <button class="ph-btn" onclick="window['${{pid}}'](- 1)">◀</button>
          <span class="ph-cnt">${{idx+1}} / ${{n}}</span>
          <button class="ph-btn" onclick="window['${{pid}}'](1)">▶</button>
        </div>`:''}}"
        <div class="pname">${{p.name}}</div>
        <div class="pdate">${{p.date||'날짜 없음'}}</div>
        <div class="pcoord">${{p.lat}}, ${{p.lng}}</div>
      </div>`;
    }}

    window[pid]=function(d){{
      cur=(cur+d+n)%n;
      marker.getPopup().setContent(buildPopup(cur));
    }};

    marker.bindPopup(buildPopup(0),{{maxWidth:260}});
  }});

  if(bounds.length===1){{
    map.setView(bounds[0],15);
  }}else{{
    map.fitBounds(bounds,{{padding:[40,40]}});
  }}
}}
</script>
</body>
</html>"""

    OUTPUT_HTML.write_text(html, encoding='utf-8')
    print(f"\\n✅ index.html 생성 완료 — {len(photos_data)}장 / {len(clusters)}곳")

if __name__ == "__main__":
    main()
