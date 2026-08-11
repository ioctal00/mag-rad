# Napomena o sestoj R6 domeni

Ovaj release cuva izvorno objavljene izvedene tabele i figure. Naknadni offline audit utvrdio je da je vrijednost `false` za indikator reparticionisanja bila izgubljena pri numerickoj konverziji, iako su regionalni planovi bili dostupni i uspjesno parsirani.

Obrazlozenje ispravke nalazi se u [`docs/05-feedback-loop-r6-correction.md`](../../docs/05-feedback-loop-r6-correction.md), a korigovani audit, tabele i figure u [`releases/feedback-loop-r6-correction-v1/`](../feedback-loop-r6-correction-v1/). Arhivirani fajlovi u ovom direktoriju nisu prepisani.
