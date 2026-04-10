'use client';

import { useState, useEffect, useRef } from 'react';

/**
 * Types out an array of lines character-by-character.
 * Returns the lines displayed so far (full + partial current line).
 * Calls onComplete when all lines have been typed.
 */
export function useTypewriter(
  lines: string[],
  speed = 22,
  onComplete?: () => void,
) {
  const [displayedLines, setDisplayedLines] = useState<string[]>([]);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  useEffect(() => {
    if (lines.length === 0) {
      setDisplayedLines([]);
      onCompleteRef.current?.();
      return;
    }

    setDisplayedLines([]);

    let lineIdx = 0;
    let charIdx = 0;
    let mounted = true;

    const tick = () => {
      if (!mounted) return;

      if (lineIdx >= lines.length) {
        onCompleteRef.current?.();
        return;
      }

      const line = lines[lineIdx];

      if (charIdx <= line.length) {
        const partial = line.slice(0, charIdx);
        setDisplayedLines((prev) => {
          const next = [...prev];
          next[lineIdx] = partial;
          return next;
        });
        charIdx++;

        // Pause longer at end of each line
        const delay = charIdx > line.length ? 200 : speed;
        setTimeout(tick, delay);
      } else {
        lineIdx++;
        charIdx = 0;
        setTimeout(tick, speed);
      }
    };

    // Small initial delay before typing starts
    const t = setTimeout(tick, 120);

    return () => {
      mounted = false;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(lines), speed]);

  return { displayedLines };
}
