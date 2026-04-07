import os, json, struct
from pathlib import Path

PHOTOS_DIR  = Path("photos")
OUTPUT_HTML = Path("index.html")

GROUP_COLORS = {
    'A조': '#E24B4A',
    'B조': '#EF9F27',
    'C조': '#1D9E75',
    'D조': '#378ADD',
    'E조': '#7F77DD',
    'F조': '#D4537E',
}
DEFAULT_COLOR = '#888780'

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
            if p['group'] == q['group'] and \
               abs(p['lat']-q['lat']) < threshold and \
               abs(p['lng']-q['lng']) < threshold:
                cluster.append(q)
                used.add(j)
        clusters.append(cluster)
    return clusters

def main():
    photos_data = []
    exts = {'.jpg', '.jpeg', '.JPG', '.JPEG'}

    # 조별 폴더 탐색
    for group_dir in sorted(PHOTOS_DIR.iterdir()):
        if not group_dir.is_dir() or group_dir.name.startswith('.'):
            continue
        group_name = group_dir.name
        color = GROUP_COLORS.get(group_name, DEFAULT_COLOR)
        print(f"\n[{group_name}] ({color})")
        for f in sorted(group_dir.iterdir()):
            if f.suffix not in exts or f.name.startswith('.'):
                continue
            gps = extract_gps(f)
            if gps:
                lat, lon = gps
                photos_data.append({
                    "name":  f.name,
                    "lat":   lat,
                    "lng":   lon,
                    "url":   f"photos/{group_name}/{f.name}",
                    "date":  get_date(f),
                    "group": group_name,
                    "color": color,
                })
                print(f"  ✅ {f.name} → {lat}, {lon}")
            else:
                print(f"  ⚠️  {f.name} → GPS 없음, 스킵")

    clusters = cluster_photos(photos_data)
    clusters_json = json.dumps(clusters, ensure_ascii=False)
    total = len(photos_data)
    groups_json = json.dumps(GROUP_COLORS, ensure_ascii=False)

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
    header{{padding:10px 16px;background:rgba(255,255,255,.06);border-bottom:1px solid rgba(255,255,255,.1);display:flex;align-items:center;justify-content:space-between;flex-shrink:0;flex-wrap:wrap;gap:8px}}
    header h1{{font-size:1rem;font-weight:500}}
    .badge{{background:rgba(255,255,255,.1);padding:3px 10px;border-radius:20px;font-size:.78rem;color:#ccc}}
    #filters{{display:flex;gap:6px;flex-wrap:wrap;padding:8px 16px;background:rgba(255,255,255,.03);border-bottom:1px solid rgba(255,255,255,.08);flex-shrink:0}}
    .fbtn{{border:none;padding:5px 14px;border-radius:20px;cursor:pointer;font-size:.78rem;font-weight:500;opacity:.5;transition:.15s}}
    .fbtn.on{{opacity:1;color:#fff}}
    .fbtn.all{{background:rgba(255,255,255,.15);color:#fff;opacity:1}}
    #map{{flex:1}}
    .cm{{border:2.5px solid #fff;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;box-shadow:0 2px 8px rgba(0,0,0,.5);cursor:pointer;color:#fff}}
    .leaflet-popup-content{{margin:10px 12px}}
    .pw{{width:220px}}
    .ptag{{display:inline-block;font-size:11px;padding:2px 10px;border-radius:10px;color:#fff;margin-bottom:6px;font-weight:600}}
    .ph-wrap img{{width:100%;height:150px;object-fit:cover;display:block;cursor:zoom-in;border-radius:8px}}
    .ph-nav{{display:flex;align-items:center;justify-content:space-between;padding:5px 0 2px}}
    .ph-btn{{border:none;color:#fff;border-radius:6px;padding:3px 12px;cursor:pointer;font-size:14px;font-weight:600}}
    .ph-cnt{{font-size:12px;color:#666}}
    .pname{{font-size:.78rem;font-weight:600;color:#222;margin:4px 0 2px;word-break:break-all}}
    .pdate{{font-size:.73rem;color:#666}}
    .pcoord{{font-size:.7rem;color:#999;margin-top:1px}}
    #lb{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.92);z-index:99999;flex-direction:column;align-items:center;justify-content:center;gap:14px}}
    #lb.on{{display:flex}}
    #lb img{{max-width:92vw;max-height:74vh;border-radius:10px}}
    #lb .lmeta{{background:rgba(255,255,255,.12);padding:7px 18px;border-radius:20px;font-size:.82rem;text-align:center}}
    #lb .lcls{{position:absolute;top:16px;right:20px;font-size:1.7rem;cursor:pointer;opacity:.7}}
    #lb .lnav{{display:flex;gap:14px}}
    #lb .lnav button{{background:rgba(255,255,255,.15);border:none;color:#fff;padding:7px 22px;border-radius:20px;cursor:pointer;font-size:.95rem}}
    #lb .lnav button:hover{{background:rgba(255,255,255,.28)}}
  </style>
</head>
<body>
<header>
  <h1>📸 조별 포토맵</h1>
  <span class="badge" id="cnt">불러오는 중...</span>
</header>
<div id="filters"></div>
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
const GROUP_COLORS = {groups_json};
const groups = Object.keys(GROUP_COLORS);
let lbList=[], lbIdx=0;
let activeGroup='all';
let allMarkers=[];

function openLb(list,idx){{
  lbList=list; lbIdx=idx; updateLb();
  document.getElementById('lb').classList.add('on');
}}
function updateLb(){{
  const p=lbList[lbIdx];
  document.getElementById('lb-img').src=p.url;
  document.getElementById('lb-meta').textContent=
    '['+p.group+'] '+p.name+(p.date?' · '+p.date:'')+' ('+(lbIdx+1)+'/'+lbList.length+')';
}}
function lbMove(d){{lbIdx=(lbIdx+d+lbList.length)%lbList.length;updateLb();}}
function closeLb(){{document.getElementById('lb').classList.remove('on');}}
document.getElementById('lb').addEventListener('click',e=>{{if(e.target.id==='lb')closeLb();}});
document.addEventListener('keydown',e=>{{
  if(e.key==='Escape')closeLb();
  if(e.key==='ArrowLeft')lbMove(-1);
  if(e.key==='ArrowRight')lbMove(1);
}});

function updateCount(){{
  const visible=allMarkers.filter(m=>activeGroup==='all'||m.group===activeGroup);
  const pc=visible.reduce((s,m)=>s+m.photoCount,0);
  document.getElementById('cnt').textContent='📍 '+pc+'장 / '+visible.length+'곳'+(activeGroup!=='all'?' ['+activeGroup+']':'');
}}

if(!clusters.length){{
  document.getElementById('cnt').textContent='사진 없음';
  document.getElementById('map').innerHTML='<p style="text-align:center;padding:80px;color:#555">조별 폴더에 GPS 사진을 올려보세요!</p>';
  document.getElementById('filters').style.display='none';
}}else{{
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
    const color=photos[0].color;
    const group=photos[0].group;
    const sz=n>1?38:14;

    const icon=L.divIcon({{
      className:'',
      html:n>1
        ?`<div class="cm" style="width:${{sz}}px;height:${{sz}}px;background:${{color}}">${{n}}</div>`
        :`<div style="width:14px;height:14px;background:${{color}};border:2.5px solid #fff;border-radius:50%;box-shadow:0 1px 4px rgba(0,0,0,.5)"></div>`,
      iconSize:[sz,sz],iconAnchor:[sz/2,sz/2]
    }});

    const marker=L.marker([lat,lng],{{icon}}).addTo(map);
    bounds.push([lat,lng]);
    allMarkers.push({{marker,group,photoCount:n}});

    let cur=0;
    const pid='fn'+ci;

    function makePopup(idx){{
      const p=photos[idx];
      const pj=JSON.stringify(photos);
      let nav='';
      if(n>1){{
        nav=`<div class="ph-nav">
          <button class="ph-btn" style="background:${{color}}" onclick="window.${{pid}}(-1)">◀</button>
          <span class="ph-cnt">${{idx+1}} / ${{n}}</span>
          <button class="ph-btn" style="background:${{color}}" onclick="window.${{pid}}(1)">▶</button>
        </div>`;
      }}
      return `<div class="pw">
        <span class="ptag" style="background:${{color}}">${{group}}</span>
        <div class="ph-wrap">
          <img src="${{p.url}}" onerror="this.style.display='none'"
               onclick='openLb(${{pj}},${{idx}})'>
        </div>
        ${{nav}}
        <div class="pname">${{p.name}}</div>
        <div class="pdate">${{p.date||'날짜 없음'}}</div>
        <div class="pcoord">${{p.lat}}, ${{p.lng}}</div>
      </div>`;
    }}

    window[pid]=function(d){{
      cur=(cur+d+n)%n;
      marker.getPopup().setContent(makePopup(cur));
    }};
    marker.bindPopup(makePopup(0),{{maxWidth:260}});
  }});

  if(bounds.length===1) map.setView(bounds[0],15);
  else map.fitBounds(bounds,{{padding:[40,40]}});

  updateCount();

  const filtersEl=document.getElementById('filters');
  const allBtn=document.createElement('button');
  allBtn.className='fbtn all'; allBtn.textContent='전체';
  allBtn.onclick=()=>setFilter('all');
  filtersEl.appendChild(allBtn);

  groups.forEach(g=>{{
    const c=GROUP_COLORS[g];
    const btn=document.createElement('button');
    btn.className='fbtn on';
    btn.style.background=c;
    btn.textContent=g;
    btn.onclick=()=>setFilter(g);
    filtersEl.appendChild(btn);
  }});

  function setFilter(g){{
    activeGroup=g;
    allMarkers.forEach(m=>{{
      if(g==='all'||m.group===g) map.addLayer(m.marker);
      else map.removeLayer(m.marker);
    }});
    document.querySelectorAll('.fbtn').forEach(b=>{{
      b.classList.toggle('on', b.textContent===g||(g==='all'&&b.textContent==='전체'));
    }});
    updateCount();
  }}
}}
</script>
</body>
</html>"""

    OUTPUT_HTML.write_text(html, encoding='utf-8')
    print(f"\n✅ 완료 — {len(photos_data)}장 / {len(clusters)}곳")

if __name__ == "__main__":
    main()
