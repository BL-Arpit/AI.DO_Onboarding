"""Start local OCR and the onboarding app using the same Python environment."""
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parent

def main():
    load_dotenv(ROOT/'.env')
    app_url=urlsplit(os.getenv('APP_URL','http://localhost:8000'))
    ocr_url=os.getenv('ADVO_URL','http://127.0.0.1:8001').rstrip('/')
    address=urlsplit(ocr_url)
    children=[]
    try:
        try:
            if os.getenv('EXTRACTION_MODE','tesseract')=='mock_pan':
                ready=True
                print('PAN DEMO MODE: annotated mock extraction; OCR service is not started.',flush=True)
            else:
                check=httpx.get(ocr_url+'/health',timeout=2,trust_env=False)
                ready=check.is_success and check.json().get('service')=='extraction'
        except (httpx.HTTPError,ValueError):ready=False
        if not ready:
            if address.hostname not in ('localhost','127.0.0.1','::1'):
                raise RuntimeError('Configured external ADVO_URL is not ready. Check that service before starting.')
            children.append(subprocess.Popen([sys.executable,'-m','uvicorn','app.extraction_main:app','--host','127.0.0.1','--port',str(address.port or 8001)],cwd=ROOT/'vendor/advo'))
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                if children[0].poll() is not None:raise RuntimeError('OCR service stopped. Read the extraction error above.')
                try:
                    response=httpx.get(ocr_url+'/health',timeout=2,trust_env=False)
                    if response.is_success:break
                    if response.status_code==503:raise RuntimeError(response.json().get('detail','Tesseract is not ready.'))
                except httpx.HTTPError:pass
                time.sleep(.25)
            else:raise RuntimeError('OCR did not start in 30 seconds. Check its terminal error.')
        children.append(subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(app_url.port or 8000)],cwd=ROOT))
        print('Onboarding: '+os.getenv('APP_URL','http://localhost:8000'),flush=True)
        while all(child.poll() is None for child in children):time.sleep(.5)
        raise RuntimeError('An application service stopped. Read its terminal error above.')
    except KeyboardInterrupt:pass
    finally:
        for child in reversed(children):
            if child.poll() is None:child.terminate()
        for child in children:
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill()

if __name__=='__main__':
    try:main()
    except RuntimeError as exc:print(str(exc),file=sys.stderr);sys.exit(1)
