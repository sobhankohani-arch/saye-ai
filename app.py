import os, base64, mimetypes, tempfile, subprocess, shutil
from pathlib import Path
from urllib.parse import quote_plus
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Saye AI")
API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip() or None
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1").strip()
client = OpenAI(api_key=API_KEY or "missing-key", base_url=BASE_URL)
MAX_BYTES = int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024

@app.get("/", response_class=HTMLResponse)
def home():
    return (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

@app.get('/health')
def health():
    return {"ok": True}

@app.get('/manifest.webmanifest')
def manifest():
    return JSONResponse({"name":"سایه AI","short_name":"سایه AI","start_url":"/","display":"standalone","background_color":"#0e1015","theme_color":"#111318","lang":"fa","dir":"rtl","description":"دستیار هوش مصنوعی فارسی"}, media_type="application/manifest+json")

@app.get('/api/status')
def status():
    return {"configured": bool(API_KEY), "model": MODEL, "image_model": IMAGE_MODEL,
            "note": "برای پاسخ واقعی باید کلید معتبر روی سرور تنظیم شود."}

async def file_to_content(f: UploadFile):
    data = await f.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"فایل {f.filename} بزرگ‌تر از سقف {MAX_BYTES//(1024*1024)} مگابایت است.")
    mime = f.content_type or mimetypes.guess_type(f.filename or '')[0] or 'application/octet-stream'
    if mime.startswith('image/'):
        b64 = base64.b64encode(data).decode('ascii')
        return [{"type":"image_url", "image_url":{"url":f"data:{mime};base64,{b64}"}}]
    if mime.startswith('video/'):
        if not shutil.which('ffmpeg'):
            raise HTTPException(415, 'برای تحلیل ویدئو نصب ffmpeg روی سرور لازم است؛ یا چند عکس از ویدئو بفرست.')
        suffix = Path(f.filename or 'clip.mp4').suffix or '.mp4'
        with tempfile.TemporaryDirectory() as td:
            src = Path(td)/('video'+suffix); src.write_bytes(data)
            # Extract up to 4 representative frames, at 0, 25%, 50%, and 75% of a short clip.
            probe = subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(src)],capture_output=True,text=True,timeout=20)
            try: duration = max(1.0, float(probe.stdout.strip()))
            except: duration = 4.0
            out=[]
            for i, frac in enumerate((0.08,0.33,0.58,0.83)):
                stamp=min(max(0,duration*frac), max(0,duration-0.1))
                frame=Path(td)/f'f{i}.jpg'
                p=subprocess.run(['ffmpeg','-y','-ss',str(stamp),'-i',str(src),'-frames:v','1','-vf','scale=900:-1','-q:v','5',str(frame)],capture_output=True,timeout=30)
                if p.returncode==0 and frame.exists():
                    b64=base64.b64encode(frame.read_bytes()).decode('ascii')
                    out.append({"type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+b64}})
            if not out: raise HTTPException(415, 'نتوانستم فریم قابل‌خواندن از ویدئو استخراج کنم.')
            return [{"type":"text","text":f"این‌ها {len(out)} فریم نمونه از ویدئو هستند. تغییرات بین فریم‌ها را با احتیاط توصیف کن و اگر جزئیات خارج از فریم‌ها مشخص نیست، شفاف بگو."}]+out
    raise HTTPException(415, f"نوع فایل پشتیبانی نمی‌شود: {mime}")

@app.post('/api/chat')
async def chat(message: str = Form(''), files: list[UploadFile] = File(default=[])):
    if not API_KEY: raise HTTPException(503, 'سرویس هوش مصنوعی تنظیم نشده است. مدیر سرور باید OPENAI_API_KEY را تنظیم کند.')
    if not message.strip() and not files: raise HTTPException(400, 'پیام یا فایل لازم است.')
    content=[{"type":"text","text":message or 'فایل‌های فرستاده‌شده را بررسی کن و به فارسی توضیح بده.'}]
    for f in files: content += await file_to_content(f)
    try:
        response=client.chat.completions.create(model=MODEL, messages=[
            {"role":"system","content":"تو سایه‌ای، دستیار فارسی‌زبان کاربردی و صریح. پاسخ را مرحله‌به‌مرحله و قابل‌اجرا بده. برای تعمیرات، ابتدا خطرهای برق، گرما، فشار و قطعات متحرک را گوشزد کن. درباره چیزهایی که نمی‌دانی ادعای قطعی نکن. اگر درخواست جست‌وجوی تازه دارد، صادقانه بگو که این نقطه اتصال به‌تنهایی جست‌وجوی زنده انجام نمی‌دهد و لینک جست‌وجو در ابزار جداگانه موجود است."},
            {"role":"user","content":content}], max_tokens=1800)
        return {"reply":response.choices[0].message.content or 'پاسخی دریافت نشد.'}
    except HTTPException: raise
    except Exception as e: raise HTTPException(502, 'ارتباط با سرویس مدل ناموفق بود؛ کلید، آدرس API و نام مدل را بررسی کن.') from e

@app.get('/api/search')
def search(q: str):
    q=q.strip()
    if not q: raise HTTPException(400, 'عبارت جست‌وجو را وارد کن.')
    return {"query":q,"links":[{"name":"Google","url":"https://www.google.com/search?q="+quote_plus(q)},{"name":"Bing","url":"https://www.bing.com/search?q="+quote_plus(q)},{"name":"DuckDuckGo","url":"https://duckduckgo.com/?q="+quote_plus(q)}]}

@app.post('/api/image')
async def generate_image(prompt: str = Form(...)):
    if not API_KEY: raise HTTPException(503, 'برای تولید تصویر باید OPENAI_API_KEY تنظیم شود.')
    if not prompt.strip(): raise HTTPException(400, 'توضیح تصویر لازم است.')
    try:
        result=client.images.generate(model=IMAGE_MODEL, prompt=prompt.strip(), size='1024x1024')
        item=result.data[0]
        if getattr(item,'b64_json',None): return {"image":"data:image/png;base64,"+item.b64_json}
        if getattr(item,'url',None): return {"image":item.url}
        raise RuntimeError('No image payload')
    except Exception as e: raise HTTPException(502, 'تولید تصویر انجام نشد؛ بررسی کن مدل تصویر در سرویس تو فعال باشد.') from e
