import os, sys, requests
from dotenv import load_dotenv
load_dotenv()
key=os.getenv("NVIDIA_API_KEY", "")
base=os.getenv("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1/chat/completions")
root=base.rsplit("/chat/completions",1)[0]
if not key:
    print("NVIDIA_API_KEY is missing from .env")
    sys.exit(1)
print("Checking NVIDIA /v1/models ...")
r=requests.get(root+"/models",headers={"Authorization":f"Bearer {key}"},timeout=20)
print("GET /v1/models:", r.status_code)
if r.status_code != 200:
    print(r.text[:1200]); sys.exit(2)
print("The key is valid and model listing works.")
print("Now checking chat inference with the configured model ...")
model=os.getenv("STUDYAI_GEN_MODEL","openai/gpt-oss-120b")
p={"model":model,"messages":[{"role":"user","content":"Reply with exactly: StudyAI test OK"}],"max_tokens":20,"temperature":0,"stream":False}
r=requests.post(base,headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json=p,timeout=60)
print("POST /v1/chat/completions:", r.status_code)
print(r.text[:2000])
if r.status_code == 410:
    print("\nRESULT: API key works, but hosted inference is not provisioned for this organization/key.")
    print("Enable Public API Endpoints / hosted inference in NVIDIA Build, then create a new key.")
elif r.status_code == 200:
    print("\nRESULT: NVIDIA inference is working.")
