// The brand's name, in two parts: "Pattern" in the main text colour and "Blue" in the brand's blue. The text is
// still "Pattern Blue" (the markup, the accessible name); showing it in capitals is the stylesheet's.

export function Wordmark() {
  return (
    <>
      <span className="pb-wordmark__ink">Pattern</span> <span className="pb-wordmark__blue">Blue</span>
    </>
  );
}
