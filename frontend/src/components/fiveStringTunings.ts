// High to low: G2 D2 A1 E1 B0. Four-string presets stay in TuningSelect.
export const FIVE_STRING_STANDARD = [43, 38, 33, 28, 23];
export const fiveStringPresets = [
    { id: 'five-standard', name: '标准调弦（低音 B）', notes: 'B · E · A · D · G', values: FIVE_STRING_STANDARD },
    { id: 'five-half-down', name: '全降半音', notes: 'B♭ · E♭ · A♭ · D♭ · G♭', values: [42, 37, 32, 27, 22] },
    { id: 'five-whole-down', name: '全降全音', notes: 'A · D · G · C · F', values: [41, 36, 31, 26, 21] },
    { id: 'drop-a', name: 'Drop A', notes: 'A · E · A · D · G', values: [43, 38, 33, 28, 21] },
];
