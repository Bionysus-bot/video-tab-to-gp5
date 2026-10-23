export default function Botanical({ variant = 0 }: { variant?: number }) {
    return <svg className={`botanical botanical-${variant}`} viewBox="0 0 140 160" fill="none" aria-hidden="true">
        <path d="M61 151C65 115 84 75 91 17M74 108C46 108 29 89 26 72C49 72 66 86 74 108ZM84 74C104 70 116 54 117 39C98 44 87 56 84 74ZM88 47C73 40 66 24 69 11C84 21 88 32 88 47ZM65 134C85 133 101 120 106 105C86 105 72 118 65 134Z" stroke="currentColor" strokeWidth=".75" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>;
}
