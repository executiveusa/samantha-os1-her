import { useCallback, useEffect, useRef, useState } from "react";
import type { Os1Config } from "./types";

export type HoloGesture =
  | "open_palm"
  | "pinch"
  | "tap"
  | "peace"
  | "point"
  | "fist"
  | "stretch"
  | "flick_left"
  | "flick_right";

export interface VisionClawState {
  cameraActive: boolean;
  lastGesture: HoloGesture | null;
  lastReceipt: string | null;
  source: "laptop_camera" | "glasses" | "holo_command";
  error?: string;
}

/**
 * VisionClaw AX-022 browser & Electron hook for Samantha OS¹.
 * Enables eyes, ears & hands from the laptop webcam (or glasses stream) with
 * lightweight motion-flick detection and direct holo-gesture dispatch.
 */
export function useVisionClaw(config: Os1Config) {
  const [vision, setVision] = useState<VisionClawState>({
    cameraActive: false,
    lastGesture: null,
    lastReceipt: null,
    source: "laptop_camera",
  });
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<number | null>(null);
  const prevCentroids = useRef<number[]>([]);

  const sendHoloGesture = useCallback(
    async (gesture: HoloGesture, source: VisionClawState["source"] = "holo_command") => {
      try {
        const headers: Record<string, string> = {
          "Content-Type": "application/json",
          ...(config.clientToken ? { Authorization: `Bearer ${config.clientToken}` } : {}),
        };
        const res = await fetch(`${config.orchestratorUrl.replace(/\/$/, "")}/os1/vision/gesture`, {
          method: "POST",
          headers,
          body: JSON.stringify({ gesture, source }),
        });
        if (!res.ok) return null;
        const data = (await res.json()) as { matched?: boolean; receipt?: string };
        if (data.matched) {
          setVision((v) => ({ ...v, lastGesture: gesture, lastReceipt: data.receipt ?? null, source }));
        }
        return data;
      } catch {
        return null;
      }
    },
    [config.orchestratorUrl, config.clientToken],
  );

  const stopCamera = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    prevCentroids.current = [];
    setVision((v) => ({ ...v, cameraActive: false }));
  }, []);

  const startLaptopCamera = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setVision((v) => ({ ...v, error: "Camera API unavailable in this browser." }));
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 240, facingMode: "user" } });
      streamRef.current = stream;
      const video = document.createElement("video");
      video.srcObject = stream;
      video.muted = true;
      await video.play();

      const canvas = document.createElement("canvas");
      canvas.width = 64;
      canvas.height = 48;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      let prevFrame: Uint8ClampedArray | null = null;
      let lastFire = 0;

      timerRef.current = window.setInterval(() => {
        if (!ctx || video.readyState < 2) return;
        ctx.drawImage(video, 0, 0, 64, 48);
        const cur = ctx.getImageData(0, 0, 64, 48).data;
        if (prevFrame) {
          let sumX = 0;
          let count = 0;
          for (let y = 0; y < 48; y += 2) {
            for (let x = 0; x < 64; x += 2) {
              const i = (y * 64 + x) * 4;
              const diff = Math.abs(cur[i] - prevFrame[i]) + Math.abs(cur[i + 1] - prevFrame[i + 1]);
              if (diff > 70) {
                sumX += x;
                count++;
              }
            }
          }
          const now = Date.now();
          if (count > 220 && now - lastFire > 1200) {
            // Large full-frame hand raise -> open_palm stop
            lastFire = now;
            void sendHoloGesture("open_palm", "laptop_camera");
          } else if (count > 35) {
            const cx = sumX / count;
            prevCentroids.current.push(cx);
            if (prevCentroids.current.length > 4) prevCentroids.current.shift();
            if (prevCentroids.current.length === 4 && now - lastFire > 900) {
              const delta = prevCentroids.current[3] - prevCentroids.current[0];
              if (delta > 16) {
                lastFire = now;
                prevCentroids.current = [];
                void sendHoloGesture("flick_right", "laptop_camera");
              } else if (delta < -16) {
                lastFire = now;
                prevCentroids.current = [];
                void sendHoloGesture("flick_left", "laptop_camera");
              }
            }
          }
        }
        prevFrame = new Uint8ClampedArray(cur);
      }, 150);

      setVision((v) => ({ ...v, cameraActive: true, source: "laptop_camera", error: undefined }));
    } catch (err) {
      setVision((v) => ({ ...v, cameraActive: false, error: err instanceof Error ? err.message : String(err) }));
    }
  }, [sendHoloGesture]);

  useEffect(() => () => stopCamera(), [stopCamera]);

  return { vision, startLaptopCamera, stopCamera, sendHoloGesture };
}
