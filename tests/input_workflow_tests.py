#!/usr/bin/env python3
"""Renderer-level input workflow checks (run in the OF build container)."""
import argparse, hashlib, json, math, os, shutil, socket, struct, subprocess, tempfile, time, wave
from contextlib import nullcontext
from pathlib import Path
ROOT = Path('/workspace'); ENGINE = ROOT / 'engine/bin/engine'; OFFSCREEN=False; PORT=45123
def osc_knobs(values):
    def s(x):
        b=x.encode()+b'\0'; return b+b'\0'*((4-len(b)%4)%4)
    return s('/knobs')+s(',iiiiii')+b''.join(struct.pack('>i',x) for x in [*values,0])
def osc_key(key, down=1):
    def s(x):
        b=x.encode()+b'\0'; return b+b'\0'*((4-len(b)%4)%4)
    return s('/key')+s(',ii')+struct.pack('>ii',key,down)
def run(cmd, expected=0):
    prefix=[] if OFFSCREEN else ['xvfb-run','-a','-s','-screen 0 1280x720x24']
    if '--osc-port' not in cmd: cmd += ['--osc-port',str(PORT)]
    if OFFSCREEN and '--offscreen' not in cmd: cmd += ['--offscreen']
    p=subprocess.run(prefix+cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=30)
    (Path(cmd[cmd.index('--storage')+1])/'engine.log').write_text(p.stdout)
    if p.returncode != expected: raise AssertionError(f'expected {expected}, got {p.returncode}\n{p.stdout}')
def main():
    global ENGINE, OFFSCREEN, PORT
    ap=argparse.ArgumentParser(); ap.add_argument('--engine',type=Path); ap.add_argument('--offscreen',action='store_true'); ap.add_argument('--output',type=Path); ap.add_argument('--port',type=int,default=45123); args=ap.parse_args()
    if args.engine: ENGINE=args.engine.resolve()
    OFFSCREEN=args.offscreen; PORT=args.port
    if not 1024 < PORT < 65536: raise SystemExit('--port must be between 1025 and 65535')
    if args.output:
        if args.output.exists() or args.output.is_symlink(): raise SystemExit('--output must not already exist')
        args.output.mkdir(parents=True)
    if not ENGINE.exists(): raise SystemExit('engine binary missing; run inside desktop build container')
    context = tempfile.TemporaryDirectory(prefix='eyesy-input-') if not args.output else nullcontext(str(args.output))
    with context as td:
        root=Path(td); mode=root/'mode'; mode.mkdir()
        (mode/'main.lua').write_text('return {api_version=1, draw=function(ctx) eyesy.clear(ctx.audio.rms_left,ctx.audio.rms_right,ctx.trigger and 1 or 0); eyesy.circle(640,360,40+ctx.knobs[1]*100) end}')
        wav_path=root/'input.wav'
        with wave.open(str(wav_path),'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
            w.writeframes(b''.join(struct.pack('<h',int(12000*math.sin(2*math.pi*440*i/44100))) for i in range(100000)))
        ws=root/'wav-live'; wr=ws/'report.json'
        run([str(ENGINE),'--mode',str(mode),'--storage',str(ws),'--frames','20','--audio-wav',str(wav_path),'--report',str(wr)])
        st=json.loads(wr.read_text()); assert st['audio_sample_rate']==44100 and st['audio_sequence']>0 and st['audio_rms_left']>.1 and st['audio_available'] is True
        short=root/'short.wav'
        with wave.open(str(short),'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100); w.writeframes(b'\0\0'*4096)
        ws=root/'wav-eof'; wr=ws/'report.json'
        run([str(ENGINE),'--mode',str(mode),'--storage',str(ws),'--frames','90','--audio-wav',str(short),'--report',str(wr)])
        st=json.loads(wr.read_text()); assert st['audio_available'] is False
        port=PORT; rec=root/'record.json'; live=root/'live'
        cmd=([] if OFFSCREEN else ['xvfb-run','-a','-s','-screen 0 1280x720x24'])+[str(ENGINE),'--mode',str(mode),'--storage',str(live),'--frames','180','--osc-port',str(port),'--record',str(rec),'--record-limit','128','--report',str(live/'report.json')]+(['--offscreen'] if OFFSCREEN else [])
        p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True); sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); output=''
        try:
            deadline=time.monotonic()+15
            while not (live/'status.json').exists():
                if p.poll() is not None or time.monotonic()>deadline: raise AssertionError('recording engine never became ready')
                time.sleep(.02)
            sock.sendto(osc_knobs([100,200,300,400,500]),('127.0.0.1',port))
            sock.sendto(osc_key(2),('127.0.0.1',port)); sock.sendto(osc_key(2,0),('127.0.0.1',port))
            sock.sendto(osc_key(9),('127.0.0.1',port))
            p.wait(timeout=30)
            output=p.stdout.read()
            assert p.returncode==0, output
        finally:
            sock.close()
            if p.poll() is None:
                p.terminate()
                try: p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill(); p.wait(timeout=5)
            if output: (live/'engine.log').write_text(output)
        events=json.loads(rec.read_text()); assert any(e['type']=='knob' for e in events)
        kinds=[e['type'] for e in events]; assert 'hardware_key' in kinds and 'hardware_release' in kinds
        assert kinds.index('hardware_key') < kinds.index('hardware_release')
        stores=[]
        for tag in ('a','b'):
            store=root/tag; stores.append(store); run([str(ENGINE),'--mode',str(mode),'--storage',str(store),'--frames','180','--replay',str(rec),'--report',str(store/'report.json')])
        ia=next((stores[0]/'grabs').glob('*.png')); ib=next((stores[1]/'grabs').glob('*.png')); assert hashlib.sha256(ia.read_bytes()).digest()==hashlib.sha256(ib.read_bytes()).digest()
        semantic_mode = root/'semantics'; semantic_mode.mkdir()
        (semantic_mode/'main.lua').write_text('''return {api_version=1,
          update=function(ctx)
            local f=math.floor(ctx.time*60+.5)
            if f==0 then assert(ctx.midi.notes[61]==100, "N press missing"); assert(ctx.knobs[1]==.5, "wrong-channel CC leaked") end
            if f==1 then assert(ctx.midi.notes[61]==0, "N release missing"); assert(ctx.midi.notes[62]==0, "wrong-channel note leaked") end
            if f==2 then assert(ctx.trigger, "shift release did not restore hardware trigger"); assert(math.abs(ctx.knobs[1]-32/127)<.00001, "CC knob mapping missing") end
            if f==3 then assert(ctx.midi.notes[62]==90, "accepted MIDI note missing") end
            if f==4 then assert(ctx.midi.notes[62]==0, "MIDI note release missing"); assert(ctx.midi.clocks==1, "MIDI clock missing") end
          end, draw=function(ctx) eyesy.clear(0,0,0) end}''')
        semantic_events = [
          {'frame':0,'type':'key','key':ord('n')},
          {'frame':0,'type':'midi','status':0xb0,'channel':1,'a':20,'b':0},
          {'frame':1,'type':'key_release','key':ord('n')},
          {'frame':1,'type':'hardware_key','key':2},
          {'frame':1,'type':'midi','status':0x90,'channel':1,'a':61,'b':90},
          {'frame':2,'type':'hardware_release','key':2},
          {'frame':2,'type':'hardware_key','key':10},
          {'frame':2,'type':'midi','status':0xb0,'channel':0,'a':20,'b':32},
          {'frame':3,'type':'midi','status':0x90,'channel':0,'a':61,'b':90},
          {'frame':4,'type':'midi','status':0x80,'channel':0,'a':61,'b':0},
          {'frame':4,'type':'midi','status':0xf8,'channel':0,'a':0,'b':0},
        ]
        semantic_replay=root/'semantic-replay.json'; semantic_replay.write_text(json.dumps(semantic_events))
        run([str(ENGINE),'--mode',str(semantic_mode),'--storage',str(root/'semantic-store'),
             '--frames','6','--replay',str(semantic_replay)])
        bad=root/'bad.json'; bad.write_text('[{"frame":0,"type":"not-an-event"}]'); run([str(ENGINE),'--probe','--frames','2','--replay',str(bad),'--storage',str(root/'bad')],1)
    print('Input workflow renderer checks passed')
if __name__=='__main__': main()
