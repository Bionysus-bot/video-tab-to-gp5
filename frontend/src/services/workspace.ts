export type Note = {
    string: number;
    fret: number;
    kind: 'normal' | 'tie' | 'dead';
    slide?: boolean;
    hammer?: boolean;
    staccato?: boolean;
};
export type Beat = {
    duration: number;
    dotted: boolean;
    triplet: boolean;
    unresolved: ('pitch' | 'duration')[];
    notes: Note[];
    ocr_confidence?: number | null;
    pitch_evidence?: string | null;
};
export type Measure = {
    number: number;
    numerator: number;
    denominator: number;
    source: string;
    confidence: number;
    reviewed: boolean;
    issues: string[];
    beats: Beat[];
};
export type Score = {
    title: string;
    instrument: 'bass' | 'guitar';
    tempo: number;
    tuning: number[];
    settings_confirmed: boolean;
    measures: Measure[];
};
export type ReadingIssue = {
    id: string;
    kind: string;
    message: string;
    measure_index: number | null;
    number: number | null;
    beat: number | null;
    severity: string;
    source: string | null;
};
export type Revision = {
    id: string;
    parent: string | null;
    origin: string;
    created_at: string;
    score: Score;
    issues: ReadingIssue[];
    protected: string[];
    entities: {
        id: string;
        number: number;
        beats: string[];
    }[];
    manifest: {
        input_key?: string;
        rows: {
            id: string;
            source: string;
            layout: string;
        }[];
    };
};
export type Artifact = {
    id: string;
    revision: string;
    created_at: string;
    report: {
        placeholders: {
            number: number;
        }[];
        partial_bars?: {
            number: number;
        }[];
    };
};
export type Job = {
    id: string;
    status: string;
    stage: string;
    message: string;
    current: number;
    total: number;
    elapsed_seconds: number;
    cache_hits: number;
    log: string[];
    artifact: Artifact | null;
    revision: string | null;
};
export type PdfInput = {
    id: string;
    name: string;
    width: number;
    height: number;
    pages: number;
};
export type WorkspaceData = {
    state: {
        active_revision: string | null;
        latest_job: string | null;
    };
    revision: Revision | null;
    revisions: {
        id: string;
        origin: string;
        created_at: string;
        measures: number;
        issues: number;
        manual: boolean;
    }[];
    artifacts: Artifact[];
    job: Job | null;
    pdf: PdfInput | null;
};
export async function call<T>(url: string, data?: unknown, method = data === undefined ? 'GET' : 'POST'): Promise<T> {
    const response = await fetch('/api' + url, { method, headers: data === undefined ? undefined : { 'Content-Type': 'application/json' }, body: data === undefined ? undefined : JSON.stringify(data) });
    if (!response.ok) {
        let message = await response.text();
        try {
            const value = JSON.parse(message);
            message = typeof value.detail === 'string' ? value.detail : JSON.stringify(value.detail);
        }
        catch { /* plain error */ }
        throw new Error(message);
    }
    return response.json();
}
export const activeJob = (job: Job | null | undefined) => !!job && !['completed', 'partial', 'failed', 'cancelled', 'interrupted'].includes(job.status);
