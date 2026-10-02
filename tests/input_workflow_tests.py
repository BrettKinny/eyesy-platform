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
        audio_mode=root/'audio-mode'; audio_mode.mkdir()
        (audio_mode/'main.lua').write_text('return {api_version=1, draw=function(ctx) eyesy.clear(ctx.audio.rms_left,0,0) end}')
        audio_events=[]
        for tag, gain in (('audio-quiet', 0.02), ('audio-loud', 0.9), ('audio-loud2', 0.9)):
            store=root/tag
            (root/f'{tag}-replay.json').write_text(json.dumps([{'frame':0,'type':'audio','gain':gain}]))
            run([str(ENGINE),'--mode',str(audio_mode),'--storage',store,'--frames','40',
                 '--replay',str(root/f'{tag}-replay.json'),'--report',str(store/'report.json')])
        ga=next((root/'audio-quiet'/'grabs').glob('*.png')); gb=next((root/'audio-loud'/'grabs').glob('*.png'))
        gb2=next((root/'audio-loud2'/'grabs').glob('*.png'))
        assert hashlib.sha256(gb.read_bytes()).digest()==hashlib.sha256(gb2.read_bytes()).digest()
        assert ga.read_bytes()!=gb.read_bytes()
        assert json.loads((root/'audio-loud'/'report.json').read_text())['audio_rms_left']>.3
        assert json.loads((root/'audio-quiet'/'report.json').read_text())['audio_rms_left']<.05
        # Instrument parity (Phase 1/3/5): trigger tone, LED protocol, knob
        # sequencer, scene update/delete, palette cycling and key repeat.
        instrument = root / 'instrument'
        instrument.mkdir()
        (instrument / 'main.lua').write_text('''return {api_version=1,
  setup=function(ctx)
    eyesy.param("size", .5, 0, 1, 3)
    eyesy.param("tone", .5, 0, 1, 1)
  end,
  draw=function(ctx)
    eyesy.clear(ctx.params.size * .4, ctx.auto_clear and .2 or 0, ctx.params.tone * .3)
    eyesy.circle(80 + (ctx.time * 900) % 1100, 360, 20 + ctx.params.size * 100)
  end}''')
        led = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        led.bind(('127.0.0.1', 0)); led.settimeout(.05)
        led_port = led.getsockname()[1]
        store = root / 'instrument-store'
        cmd = ([] if OFFSCREEN else ['xvfb-run', '-a', '-s', '-screen 0 1280x720x24']) + [
            str(ENGINE), '--mode', str(instrument), '--storage', str(store), '--frames', '1200',
            '--osc-port', str(port), '--led-port', str(led_port),
            '--report', str(store / 'report.json')] + (['--offscreen'] if OFFSCREEN else [])
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        output = ''
        codes = []
        try:
            deadline = time.monotonic() + 15
            while not (store / 'status.json').exists():
                if p.poll() is not None or time.monotonic() > deadline:
                    raise AssertionError('instrument engine never became ready')
                time.sleep(.02)
            isock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            def status():
                try:
                    return json.loads((store / 'status.json').read_text())
                except (OSError, ValueError):
                    return {}
            def wait_for(predicate, label, timeout=3):
                # status.json is rewritten once a second, so poll rather than
                # sampling a stale snapshot.
                end = time.monotonic() + timeout
                state = {}
                while time.monotonic() < end:
                    state = status()
                    if predicate(state):
                        return state
                    time.sleep(.1)
                raise AssertionError((label, state))
            def drain(seconds=.5):
                end = time.monotonic() + seconds
                while time.monotonic() < end:
                    try:
                        data, _ = led.recvfrom(1024)
                    except socket.timeout:
                        continue
                    if len(data) >= 16 and data.startswith(b'/led'):
                        codes.append(struct.unpack('>i', data[-4:])[0])
            def key(number, down=1):
                isock.sendto(osc_key(number, down), ('127.0.0.1', port))
            def knobs(values):
                isock.sendto(osc_knobs(values), ('127.0.0.1', port))
            drain(.4)
            assert codes and codes[0] == 7, ('startup LED', codes)
            key(2); key(10)                       # Shift + Trigger arms the sequencer
            drain(.4)
            assert 6 in codes, ('armed LED', codes)
            deadline = time.monotonic() + 3
            tone = {}
            while time.monotonic() < deadline:    # holding trigger synthesises the test tone
                tone = status()
                if tone.get('audio_synthesizing') and tone.get('audio_rms_left', 0) > .3:
                    break
                time.sleep(.05)
            assert tone.get('audio_synthesizing'), ('trigger tone', tone)
            assert tone.get('audio_rms_left', 0) > .3, ('trigger level', tone)
            key(10, 0); key(2, 0)
            deadline = time.monotonic() + 3
            released = {}
            while time.monotonic() < deadline:    # status.json lags by up to a second
                released = status()
                if not released.get('audio_synthesizing'):
                    break
                time.sleep(.1)
            assert not released.get('audio_synthesizing'), ('tone kept running', released)
            knobs([500, 500, 900, 500, 500])      # knob 3 moves -> recording starts
            drain(.4)
            assert 1 in codes, ('recording LED', codes)
            for value in (700, 400, 800, 300):
                knobs([500, 500, value, 500, 500]); time.sleep(.08)
            key(2); key(9)                        # Shift + Screenshot -> playback
            drain(.4)
            assert 3 in codes, ('playing LED', codes)
            key(9, 0); key(2, 0)
            first = {}
            for index, code in enumerate(codes):
                first.setdefault(code, index)
            assert all(code in first for code in (7, 6, 1, 3)), ('LED codes', codes)
            reached = [first[code] for code in (7, 6, 1, 3)]
            assert reached == sorted(reached), ('LED order', codes)
            key(8); time.sleep(.15); key(8, 0)    # quick press saves on release
            time.sleep(.5)
            scenes = sorted((store / 'scenes').glob('*.json'))
            assert len(scenes) == 1, scenes
            saved = json.loads(scenes[0].read_text())
            assert len(saved['knob_sequence']) > 1, saved.keys()
            assert saved['fg_palette'] == 0 and saved['bg_palette'] == 0
            playing = wait_for(lambda s: s.get('sequencer') == 'playing', 'sequencer playing')
            assert playing.get('sequencer_frames', 0) > 1, playing
            key(2); key(9); key(9, 0); key(2, 0)  # stop the sequence
            wait_for(lambda s: s.get('sequencer') == 'stopped', 'sequencer stopped')
            key(7)                                # recall restores the running sequence
            time.sleep(.15)
            key(7, 0)
            wait_for(lambda s: s.get('sequencer') == 'playing', 'sequence restored')
            key(2); key(9); key(9, 0); key(2, 0)  # stop again before updating
            wait_for(lambda s: s.get('sequencer') == 'stopped', 'sequencer stopped again')
            knobs([200, 500, 900, 500, 500])      # knob 1 writes tone
            time.sleep(.4)
            key(2); key(8); time.sleep(.15); key(8, 0); key(2, 0)   # Shift + Save updates
            time.sleep(.5)
            updated = json.loads(scenes[0].read_text())
            assert abs(updated['parameters']['tone'] - .2) < .02, updated['parameters']
            assert 'knob_sequence' not in updated, 'stopped sequence kept on update'
            key(8)                                # hold past the delete window
            time.sleep(1.4)
            key(8, 0)
            time.sleep(.5)
            assert not list((store / 'scenes').glob('*.json')), 'scene not deleted'
            key(2); key(4); time.sleep(.15); key(4, 0)
            state = wait_for(lambda s: s.get('fg_palette') != 0, 'previous palette')
            count = state.get('palette_count', 0)
            assert count > 10, ('palette table', state)
            palettes = state.get('fg_palette')
            assert palettes == count - 1, ('previous palette', palettes)
            key(5)                                # hold: the repeater must cycle
            time.sleep(.8)
            key(5, 0); key(2, 0)
            repeated = wait_for(
                lambda s: s.get('fg_palette') not in (palettes, (palettes + 1) % count),
                'repeater did not cycle')['fg_palette']
            assert repeated != palettes and repeated != (palettes + 1) % count, (
                'repeater did not cycle', palettes, repeated)
            isock.close()
            p.wait(timeout=40)
            output = p.stdout.read()
            assert p.returncode == 0, output
        finally:
            led.close()
            if p.poll() is None:
                p.terminate()
                try: p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill(); p.wait(timeout=5)
            if output: (store / 'engine.log').write_text(output)
        settled = json.loads((store / 'report.json').read_text())
        assert settled['sequencer'] == 'stopped' and settled['led'] == 7, settled
        # Configuration menu (Phase 5): navigation, value changes and config
        # persistence for the video, audio and palette screens.
        menu_cmd = ([] if OFFSCREEN else ['xvfb-run', '-a', '-s', '-screen 0 1280x720x24']) + [
            str(ENGINE), '--mode', str(instrument), '--storage', str(store), '--frames', '900',
            '--osc-port', str(port), '--report', str(store / 'report.json')] + (
            ['--offscreen'] if OFFSCREEN else [])
        (store / 'status.json').unlink(missing_ok=True)
        p = subprocess.Popen(menu_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        output = ''
        try:
            deadline = time.monotonic() + 15
            while not (store / 'status.json').exists():
                if p.poll() is not None or time.monotonic() > deadline:
                    raise AssertionError('menu engine never became ready')
                time.sleep(.02)
            msock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            def mstatus():
                try:
                    return json.loads((store / 'status.json').read_text())
                except (OSError, ValueError):
                    return {}
            def wait_menu(predicate, label, timeout=4):
                end = time.monotonic() + timeout
                state = {}
                while time.monotonic() < end:
                    state = mstatus()
                    if predicate(state):
                        return state
                    time.sleep(.1)
                raise AssertionError((label, state))
            def mkey(number, down=1):
                msock.sendto(osc_key(number, down), ('127.0.0.1', port))
            def press(number):
                mkey(number); time.sleep(.15); mkey(number, 0)
            def combo(number):
                mkey(2); time.sleep(.1); press(number); time.sleep(.1); mkey(2, 0)
            wait_menu(lambda s: s.get('mode') == 'instrument', 'mode ready')
            combo(1)                              # Shift + OSD opens the menu
            wait_menu(lambda s: s.get('menu_screen') == 0, 'menu home')
            press(1)                              # OSD backs out of the home screen
            wait_menu(lambda s: s.get('menu_screen') == -1, 'menu closed')
            config_path = store / 'config.json'
            assert config_path.exists(), 'menu close did not persist config'
            combo(1)
            wait_menu(lambda s: s.get('menu_screen') == 0, 'menu home again')
            press(7); press(8)                    # down to Audio & MIDI, enter
            wait_menu(lambda s: s.get('menu_screen') == 2, 'audio screen')
            press(5); press(5)                    # gain up two steps
            press(1)                              # back to home
            wait_menu(lambda s: s.get('menu_screen') == 0, 'home from audio')
            press(7); press(7); press(8)          # down to Palettes, enter
            wait_menu(lambda s: s.get('menu_screen') == 3, 'palette screen')
            press(5)                              # next FG palette
            press(1)                              # back to home
            press(7); press(7); press(7); press(8)   # down to Hardware test, enter
            wait_menu(lambda s: s.get('menu_screen') == 4, 'test screen')
            # Diagnostic rows arm against the live hardware, then require real
            # movement: two pots swept and three buttons pressed.
            msock.sendto(osc_knobs([900, 200, 500, 500, 500]), ('127.0.0.1', port))
            msock.sendto(osc_knobs([900, 200, 700, 500, 500]), ('127.0.0.1', port))
            for _ in range(3):
                press(3)
            tested = wait_menu(lambda s: s.get('diagnostics', {}).get('pots')
                               and s['diagnostics'].get('buttons'), 'diagnostics', timeout=5)
            assert tested['diagnostics']['pots'] and tested['diagnostics']['buttons'], tested
            assert not tested['diagnostics']['midi'], 'MIDI row needs a real note'
            press(1); press(1)                    # home, then exit (persists config)
            wait_menu(lambda s: s.get('menu_screen') == -1, 'menu exit')
            saved_settings = json.loads(config_path.read_text())
            assert saved_settings['audio_gain'] > 1, saved_settings
            assert saved_settings['fg_palette'] == 1, saved_settings
            assert saved_settings['schema_version'] == 1, saved_settings
            assert 'video_mode' in saved_settings, saved_settings
            msock.close()
            p.wait(timeout=40)
            output = p.stdout.read()
            assert p.returncode == 0, output
        finally:
            if p.poll() is None:
                p.terminate()
                try: p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill(); p.wait(timeout=5)
            if output: (store / 'menu-engine.log').write_text(output)
        # Closing the menu with the keyboard M toggle persists like Back does:
        # M, Down to Audio & MIDI, Return, Right x2 (gain up), M.
        m_keys=[ord('m'),0xe00F,13,0xe00E,0xe00E,ord('m')]
        m_replay=root/'menu-m.json'; m_replay.write_text(json.dumps([{'frame':i+1,'type':'key','key':k} for i,k in enumerate(m_keys)]))
        m_store=root/'menu-m-store'; run([str(ENGINE),'--mode',str(mode),'--storage',str(m_store),'--frames','12','--replay',str(m_replay)])
        m_saved=json.loads((m_store/'config.json').read_text()); assert m_saved['audio_gain']>1, ('M close did not persist', m_saved)
        bad_audio=root/'bad-audio.json'; bad_audio.write_text('[{"frame":0,"type":"audio","gain":9}]')
        bad=root/'bad.json'; bad.write_text('[{"frame":0,"type":"not-an-event"}]')
        prefix=[] if OFFSCREEN else ['xvfb-run','-a','-s','-screen 0 1280x720x24']
        for replay_path, message in ((bad_audio, 'invalid audio event'), (bad, 'unknown input event')):
            p=subprocess.run(prefix+[str(ENGINE),'--mode',str(mode),'--frames','2','--replay',
                                     str(replay_path),'--storage',str(root/replay_path.stem)],
                             stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=30)
            assert p.returncode==1 and message in p.stdout, (message, p.returncode, p.stdout)
    print('Input workflow renderer checks passed')
if __name__=='__main__': main()
