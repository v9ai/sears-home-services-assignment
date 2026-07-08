/**
 * TypeScript mirror of the frozen contracts in `app/contracts.py`
 * (COORDINATION.md §2). Keep byte-identical to the WS frame shapes and the
 * CaseFile shape documented in
 * specs/features/2026-07-08-voice-diagnostic-core/requirements.md — this file
 * does not redefine the contract, it restates it for the thin client.
 */

export type Appliance =
  | "washer"
  | "dryer"
  | "refrigerator"
  | "dishwasher"
  | "oven"
  | "hvac";

export interface Symptom {
  description: string;
  onset: string;
  error_code?: string | null;
  sound?: string | null;
}

export interface Customer {
  name?: string | null;
  zip?: string | null;
  email?: string | null;
}

export interface CaseFile {
  appliance_type: Appliance | null;
  brand: string | null;
  model: string | null;
  symptoms: Symptom[];
  safety_flag: boolean;
  steps_given: string[];
  customer: Customer;
}

export interface UserTextFrame {
  type: "user_text";
  text: string;
}

export interface TranscriptFrame {
  type: "transcript";
  role: "user" | "agent";
  text: string;
}

export interface AudioFrame {
  type: "audio";
  chunk: string; // base64
  seq: number;
  // "pcm24k" = raw mono PCM16 LE @ 24 kHz (gapless WebAudio path). Absent or
  // "mp3" = legacy mp3 blob chunks (fallback <audio> path).
  format?: "pcm24k" | "mp3";
}

export interface StateFrame {
  type: "state";
  case_file: CaseFile;
}

export type ServerFrame = TranscriptFrame | AudioFrame | StateFrame;

export interface TranscriptLine {
  role: "user" | "agent";
  text: string;
}

export const EMPTY_CASE_FILE: CaseFile = {
  appliance_type: null,
  brand: null,
  model: null,
  symptoms: [],
  safety_flag: false,
  steps_given: [],
  customer: {},
};

// Call Recording & In-App Replay (specs/features/2026-07-08-call-recording-replay).
export type RecordingChannel = "web" | "phone";

export interface RecordingListItem {
  id: string;
  channel: RecordingChannel;
  started_at: string;
  ended_at: string | null;
  appliance_type: Appliance | null;
  turn_count: number;
  has_call_sid: boolean;
}

export interface RecordingTranscriptTurn {
  role: "user" | "agent";
  text: string;
  ts: string | null;
  has_audio: boolean;
  audio_seq: number | null;
}

// Native Twilio call recording (console.twilio.com/us1/monitor/logs/call-recordings),
// looked up live via the Twilio REST API — distinct from this app's own per-turn
// WAV/MP3 capture above.
export interface TwilioRecordingInfo {
  sid: string;
  status: string | null;
  duration_seconds: number | null;
  channels: number | null;
  date_created: string | null;
  media_url: string;
}

export interface RecordingDetail {
  transcript: RecordingTranscriptTurn[];
  case_file: CaseFile;
  twilio_recordings: TwilioRecordingInfo[];
}
