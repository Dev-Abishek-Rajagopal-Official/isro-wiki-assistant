/**
 * Voice input: record with MediaRecorder, then convert to 16 kHz mono 16-bit PCM WAV (the format verified
 * with Azure Fast Transcription), whatever container the browser records in.
 */

export const TARGET_RATE = 16000;

/** Encode mono float samples [-1, 1] as a 16-bit PCM WAV file. */
export function encodeWav(samples: Float32Array, sampleRate = TARGET_RATE): ArrayBuffer {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buffer);
  const str = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF");
  v.setUint32(4, 36 + samples.length * 2, true);
  str(8, "WAVE");
  str(12, "fmt ");
  v.setUint32(16, 16, true);          // PCM chunk size
  v.setUint16(20, 1, true);           // PCM
  v.setUint16(22, 1, true);           // mono
  v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true);
  v.setUint16(32, 2, true);           // block align
  v.setUint16(34, 16, true);          // bits per sample
  str(36, "data");
  v.setUint32(40, samples.length * 2, true);
  samples.forEach((s, i) => {
    const x = Math.max(-1, Math.min(1, s));
    v.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7fff, true);
  });
  return buffer;
}

export function toBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

/** Decode any recorded blob and resample to 16 kHz mono. */
export async function blobToWav(blob: Blob): Promise<ArrayBuffer> {
  const ctx = new AudioContext();
  try {
    const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
    const frames = Math.ceil(decoded.duration * TARGET_RATE);
    const offline = new OfflineAudioContext(1, frames, TARGET_RATE);
    const src = offline.createBufferSource();
    src.buffer = decoded;
    src.connect(offline.destination);
    src.start();
    const rendered = await offline.startRendering();
    return encodeWav(rendered.getChannelData(0), TARGET_RATE);
  } finally {
    void ctx.close();
  }
}

/** Minimal recorder: start() asks for the microphone, stop() resolves with WAV bytes as base64. */
export class VoiceRecorder {
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private stream: MediaStream | null = null;

  static supported(): boolean {
    return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";
  }

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.chunks = [];
    this.recorder = new MediaRecorder(this.stream);
    this.recorder.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
    this.recorder.start();
  }

  stop(): Promise<string> {
    return new Promise((resolve, reject) => {
      const rec = this.recorder;
      if (!rec) return reject(new Error("not recording"));
      rec.onstop = async () => {
        this.stream?.getTracks().forEach((t) => t.stop());
        try {
          const blob = new Blob(this.chunks, { type: rec.mimeType });
          resolve(toBase64(await blobToWav(blob)));
        } catch (e) {
          reject(e);
        }
      };
      rec.stop();
    });
  }

  cancel(): void {
    this.recorder?.state === "recording" && this.recorder.stop();
    this.stream?.getTracks().forEach((t) => t.stop());
  }
}
