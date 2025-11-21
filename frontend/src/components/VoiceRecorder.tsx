import { useState, useRef, useCallback, useEffect } from "react";
import { Mic } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { GROQ_API_KEY } from "@/config";
import { MicrophoneWaveform } from "@/components/ui/waveform";

interface VoiceRecorderProps {
  onTranscription: (text: string) => void;
  disabled?: boolean;
  className?: string;
}

export const VoiceRecorder = ({ onTranscription, disabled = false, className }: VoiceRecorderProps) => {
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: 'audio/webm;codecs=opus'
      });

      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        // Stop all tracks to release the microphone
        stream.getTracks().forEach(track => track.stop());
        streamRef.current = null;

        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });

        // Convert WebM to WAV for better compatibility
        const audioBuffer = await audioBlob.arrayBuffer();
        const tempAudioContext = new AudioContext();
        const audioBufferDecoded = await tempAudioContext.decodeAudioData(audioBuffer);
        tempAudioContext.close();

        // Create WAV file
        const wavBuffer = audioBufferToWav(audioBufferDecoded);
        const wavBlob = new Blob([wavBuffer], { type: 'audio/wav' });

        await processAudio(wavBlob);
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (error) {
      console.error('Error starting recording:', error);
      // Handle microphone permission denied or other errors
    }
  }, []);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
      setIsProcessing(true);
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
      }
    };
  }, []);

  const processAudio = async (audioBlob: Blob) => {
    try {
      const formData = new FormData();
      formData.append('file', audioBlob, 'recording.wav');
      formData.append('model', 'whisper-large-v3-turbo');
      formData.append('response_format', 'json');

      const response = await fetch('https://api.groq.com/openai/v1/audio/transcriptions', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${GROQ_API_KEY}`,
        },
        body: formData,
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const result = await response.json();
      const transcribedText = result.text?.trim();

      if (transcribedText) {
        onTranscription(transcribedText);
      }
    } catch (error) {
      console.error('Error processing audio:', error);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleClick = () => {
    if (disabled || isProcessing) return;

    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  };

  // Convert AudioBuffer to WAV format
  const audioBufferToWav = (buffer: AudioBuffer): ArrayBuffer => {
    const length = buffer.length;
    const sampleRate = buffer.sampleRate;
    const numChannels = buffer.numberOfChannels;

    const arrayBuffer = new ArrayBuffer(44 + length * numChannels * 2);
    const view = new DataView(arrayBuffer);

    // WAV header
    const writeString = (offset: number, string: string) => {
      for (let i = 0; i < string.length; i++) {
        view.setUint8(offset + i, string.charCodeAt(i));
      }
    };

    writeString(0, 'RIFF');
    view.setUint32(4, 36 + length * numChannels * 2, true);
    writeString(8, 'WAVE');
    writeString(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * numChannels * 2, true);
    view.setUint16(32, numChannels * 2, true);
    view.setUint16(34, 16, true);
    writeString(36, 'data');
    view.setUint32(40, length * numChannels * 2, true);

    // Write audio data
    let offset = 44;
    for (let i = 0; i < length; i++) {
      for (let channel = 0; channel < numChannels; channel++) {
        const sample = Math.max(-1, Math.min(1, buffer.getChannelData(channel)[i]));
        view.setInt16(offset, sample * 0x7FFF, true);
        offset += 2;
      }
    }

    return arrayBuffer;
  };

  return (
    <div className="relative flex items-center justify-center">
      <Button
        type="button"
        size="icon"
        onClick={handleClick}
        disabled={disabled || isProcessing}
        className={cn(
          "shrink-0 relative transition-all duration-500 ease-out",
          // Remove background circle and use transparent background
          "bg-transparent border-none hover:bg-transparent",
          // Expanded cylindrical shape when recording
          isRecording && "w-52 min-h-10",
          // Processing state
          isProcessing && "opacity-50",
          // Ensure button stays centered
          "flex items-center justify-center",
          className
        )}
      >
        {/* Mic Icon - visible when not recording */}
        {!isRecording && !isProcessing && (
          <Mic className="h-4 w-4 text-foreground transition-all duration-300" />
        )}

        {/* Processing Spinner */}
        {isProcessing && (
          <div className="animate-spin rounded-full h-4 w-4 border-2 border-yellow-500 border-t-transparent" />
        )}

        {/* Recording State - MicrophoneWaveform visualization */}
        {isRecording && (
          <div className="flex items-center justify-center w-full h-full gap-2 px-2">
            {/* Waveform container - takes most space */}
            <div className="flex-1 min-w-0 h-full flex items-center overflow-hidden">
              <div className="w-full h-full">
                <MicrophoneWaveform
                  active={isRecording}
                  height={28}
                  sensitivity={3.0}
                  barWidth={2}
                  barGap={1}
                  dynamicColor={true}
                  onError={(error) => console.error("Microphone error:", error)}
                />
              </div>
            </div>

            {/* Recording pulse indicator - fixed small space */}
            <div className="flex-shrink-0 flex items-center justify-center w-6 h-full">
              <div className="relative">
                <div className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
                <div className="absolute inset-0 w-4 h-4 border border-red-400 rounded-full animate-ping -m-1" />
              </div>
            </div>
          </div>
        )}
      </Button>
    </div>
  );
};