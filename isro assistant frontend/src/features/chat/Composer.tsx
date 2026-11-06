/**
 * Message box: text (Enter sends, Shift+Enter new line) or voice (record -> 16 kHz WAV -> ask_audio).
 * While a run is active the send button becomes Stop.
 */
import { Mic, SendHorizontal, Square, X } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { cx } from "../../components/ui";
import { VoiceRecorder } from "../../lib/audio";

export function Composer({ busy, disabled, onSend, onVoice, onStop, placeholder }: {
  busy: boolean; disabled?: boolean; placeholder?: string;
  onSend: (text: string) => void; onVoice: (wavBase64: string) => void; onStop: () => void;
}) {
  const [text, setText] = useState("");
  const [recording, setRecording] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [micError, setMicError] = useState("");
  const recorder = useRef<VoiceRecorder | null>(null);
  const area = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!recording) return;
    const t = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [recording]);

  useEffect(() => {
    const el = area.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
    }
  }, [text]);

  const send = () => {
    const q = text.trim();
    if (!q || busy || disabled) return;
    onSend(q);
    setText("");
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  };

  const startRecording = async () => {
    setMicError("");
    try {
      recorder.current = new VoiceRecorder();
      await recorder.current.start();
      setSeconds(0);
      setRecording(true);
    } catch {
      setMicError("Microphone not available - allow access in your browser and try again.");
    }
  };

  const stopRecording = async () => {
    setRecording(false);
    setPreparing(true);
    try {
      const b64 = await recorder.current!.stop();
      onVoice(b64);
    } catch {
      setMicError("Couldn't process the recording - please try again.");
    } finally {
      setPreparing(false);
    }
  };

  const cancelRecording = () => {
    recorder.current?.cancel();
    setRecording(false);
  };

  return (
    <div className="mx-auto w-full max-w-3xl px-3 pb-4 sm:px-6">
      {micError && <p className="mb-2 text-xs text-red-600">{micError}</p>}
      <div className={cx("flex items-end gap-2 rounded-2xl border bg-white p-2 shadow-sm transition focus-within:border-brand-400 focus-within:ring-4 focus-within:ring-brand-50",
        recording ? "border-red-300" : "border-slate-300")}>
        {recording ? (
          <div className="flex flex-1 items-center gap-3 px-2 py-2 text-sm text-slate-700">
            <span className="relative flex h-3 w-3"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75" /><span className="relative inline-flex h-3 w-3 rounded-full bg-red-500" /></span>
            Recording… {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
            <button onClick={cancelRecording} className="ml-auto inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800"><X className="h-3.5 w-3.5" /> Cancel</button>
          </div>
        ) : (
          <textarea ref={area} rows={1} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey}
            disabled={disabled || preparing} aria-label="Your question"
            placeholder={preparing ? "Preparing your recording…" : placeholder ?? "Ask about ISRO missions, satellites, launches…"}
            className="max-h-[200px] flex-1 resize-none bg-transparent px-2 py-2 text-[15px] outline-none placeholder:text-slate-400" />
        )}
        {!busy && VoiceRecorder.supported() && (
          <button onClick={recording ? stopRecording : startRecording} disabled={disabled || preparing}
            aria-label={recording ? "Stop recording and send" : "Ask by voice"} title={recording ? "Stop and send" : "Ask by voice"}
            className={cx("flex h-10 w-10 shrink-0 items-center justify-center rounded-xl transition disabled:opacity-40",
              recording ? "bg-red-500 text-white hover:bg-red-600" : "text-slate-500 hover:bg-slate-100 hover:text-brand-700")}>
            {recording ? <SendHorizontal className="h-5 w-5" /> : <Mic className="h-5 w-5" />}
          </button>
        )}
        {busy ? (
          <button onClick={onStop} aria-label="Stop" title="Stop"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-800 text-white hover:bg-slate-700">
            <Square className="h-4 w-4 fill-current" />
          </button>
        ) : !recording && (
          <button onClick={send} disabled={!text.trim() || disabled} aria-label="Send" title="Send"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-600 text-white transition hover:bg-brand-700 disabled:bg-slate-200 disabled:text-slate-400">
            <SendHorizontal className="h-5 w-5" />
          </button>
        )}
      </div>
      <p className="mt-1.5 text-center text-[11px] text-slate-400">Answers come from Wikipedia and live space-data sources and cite them. Check important facts.</p>
    </div>
  );
}
