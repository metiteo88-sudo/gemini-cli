"""Run the REAL fva.py; only the Edge network call is replaced. Captures what Farid would receive."""
import sys, subprocess, json, pathlib
sys.path.insert(0, '.')
import fva
SENT = []
async def fake_edge(text, out, voice=None, rate=None, is_ssml=False, **k):
    SENT.append({"voice": voice, "rate": rate, "is_ssml": is_ssml, "text": text})
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                    "-t", "0.2", "-q:a", "9", "-f", "mp3", out], check=True)
fva.edge_generate_voice = fake_edge
OUT = sys.argv[2]
sys.argv = ["fva.py", sys.argv[1], "--output-dir", OUT]
try:
    fva.main()
finally:
    pathlib.Path(OUT, "sent_to_farid.json").write_text(json.dumps(SENT, ensure_ascii=False, indent=1), encoding="utf-8")
    print("chunks sent:", len(SENT))
