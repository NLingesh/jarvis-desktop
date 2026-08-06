import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createNote, getBaseUrl, getMeta, listNotes, searchNotes } from '../api/vault';

function jsonResponse(body: unknown) {
  return { ok: true, status: 200, json: async () => body } as Response;
}

describe('vault API client', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('serverUrl', 'localhost:8000');
  });

  it('builds the base URL from stored serverUrl', () => {
    expect(getBaseUrl()).toBe('http://localhost:8000');
    localStorage.setItem('serverUrl', 'http://127.0.0.1:9000/');
    expect(getBaseUrl()).toBe('http://127.0.0.1:9000');
  });

  it('creates a note via POST', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        note: {
          path: 'Knowledge/Test.md',
          title: 'Test',
          tags: [],
          body: 'hi',
          folder: 'Knowledge',
        },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const note = await createNote({ title: 'Test', content: 'hi', folder: 'Knowledge' });
    expect(note.path).toBe('Knowledge/Test.md');
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toMatchObject({ title: 'Test', content: 'hi' });
  });

  it('lists notes with query params', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ notes: [{ title: 'A' }] }));
    vi.stubGlobal('fetch', fetchMock);

    const notes = await listNotes({ tag: 'work' });
    expect(notes).toHaveLength(1);
    expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8000/api/vault/notes?tag=work');
  });

  it('searches with url-encoded params', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ results: [] }));
    vi.stubGlobal('fetch', fetchMock);

    await searchNotes({ q: 'hello world', limit: 5 });
    expect(fetchMock.mock.calls[0][0]).toContain('q=hello+world');
    expect(fetchMock.mock.calls[0][0]).toContain('limit=5');
  });

  it('loads meta', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ meta: { total: 3, root: '/vault' } }));
    vi.stubGlobal('fetch', fetchMock);
    const meta = await getMeta();
    expect(meta.total).toBe(3);
  });
});
