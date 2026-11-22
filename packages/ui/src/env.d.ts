declare module "*.css";
declare module "*.mp3" {
  const src: string;
  export default src;
}
declare module "@novnc/novnc" {
  export default class RFB {
    constructor(target: HTMLElement, url: string, options?: { credentials?: { password?: string } });
    viewOnly: boolean;
    scaleViewport: boolean;
    resizeSession: boolean;
    clipViewport: boolean;
    qualityLevel: number;
    compressionLevel: number;
    showDotCursor: boolean;
    addEventListener(type: string, listener: (ev: CustomEvent) => void): void;
    disconnect(): void;
  }
}

interface ImportMeta {
  glob<T = unknown>(
    pattern: string | string[],
    options?: { eager?: boolean; import?: string },
  ): Record<string, T>;
}
