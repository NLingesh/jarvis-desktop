export function getBaseUrl(): string {
  const server = localStorage.getItem('serverUrl') || 'localhost:8000';
  const trimmed = server.trim().replace(/\/+$/, '');
  return trimmed.startsWith('http') ? trimmed : `http://${trimmed}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getBaseUrl()}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export function captureScreenshot(
  confirm = true,
): Promise<{ format: string; image_base64: string }> {
  return request<{ format: string; image_base64: string }>('/api/vision/screenshot', {
    method: 'POST',
    body: JSON.stringify({ confirm }),
  });
}

export function ocrImage(imageBase64: string): Promise<{ text: string }> {
  return request<{ text: string }>('/api/vision/ocr', {
    method: 'POST',
    body: JSON.stringify({ image_base64: imageBase64 }),
  });
}

export function analyzeImage(
  imageBase64: string,
  prompt = 'Describe this image in detail.',
): Promise<{ analysis: string }> {
  return request<{ analysis: string }>('/api/vision/analyze', {
    method: 'POST',
    body: JSON.stringify({ image_base64: imageBase64, prompt }),
  });
}

export function listWindows(): Promise<{ windows: any[] }> {
  return request<{ windows: any[] }>('/api/vision/windows');
}

export function focusWindow(windowId: string): Promise<{ focused: string }> {
  return request<{ focused: string }>(`/api/vision/windows/${encodeURIComponent(windowId)}/focus`, {
    method: 'POST',
  });
}
