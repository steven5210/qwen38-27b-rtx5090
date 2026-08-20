#!/usr/bin/env python3
"""Regenerate the video probe clip with LARGE legible text (the old clip's tiny
default font caused the 0/6 hallucinated-digits artifact)."""
import base64,os,random,subprocess,tempfile
from PIL import Image, ImageDraw, ImageFont
OUT_MP4="/opt/ninfer/testvid2.mp4"; OUT_B64="/opt/ninfer/testvid2.b64"; OUT_CODES="/opt/ninfer/testvid2.codes"
FONTS=["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
       "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
       "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
font=None
for f in FONTS:
    if os.path.exists(f):
        font=ImageFont.truetype(f,84); small=ImageFont.truetype(f,40); break
assert font, "no TTF font found"
random.seed(20260820)
codes=["CODE-%05d"%random.randint(10000,99999) for _ in range(6)]
tmp=tempfile.mkdtemp()
W,H,FPS,SECS=960,540,4,2
n=0
for seg,code in enumerate(codes):
    bg=[(24,32,44),(44,24,32),(32,44,24),(40,40,20),(20,40,40),(40,20,40)][seg]
    for _ in range(FPS*SECS):
        img=Image.new("RGB",(W,H),bg); d=ImageDraw.Draw(img)
        d.text((60,80),"SEGMENT %d"%(seg+1),font=small,fill=(200,200,200))
        d.text((60,220),code,font=font,fill=(255,255,120))
        img.save(os.path.join(tmp,"f%04d.png"%n)); n+=1
subprocess.run(["ffmpeg","-y","-framerate",str(FPS),"-i",os.path.join(tmp,"f%04d.png"),
                "-c:v","libx264","-pix_fmt","yuv420p","-crf","23",OUT_MP4],
               check=True,capture_output=True)
raw=open(OUT_MP4,"rb").read()
open(OUT_B64,"w").write(base64.b64encode(raw).decode())
open(OUT_CODES,"w").write("\n".join(codes)+"\n")
print("clip: %d frames, %d KB mp4, %d KB base64"%(n,len(raw)//1024,len(raw)*4//3//1024))
print("codes: "+", ".join(codes))
print("GENVID2_DONE")
