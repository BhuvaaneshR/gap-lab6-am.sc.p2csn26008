<!--
  ATTACK.md — Lab 6.

  Two halves, in this order: you attack your own application, then you defend it,
  then you run the same attacks again unchanged.

  At least two attacks. At least one of them must succeed BEFORE you build any
  defence. An attack you never got to work is not evidence, it is an assumption,
  and it scores nothing.

  What counts as evidence, from the Week 6 slide:

    The payload      the exact text, copied out of the document
                     -- not "a hidden instruction"
    The placement    which file, and where in it: body, footer, speaker note
                     -- not "somewhere in the corpus"
    What the app did the observable behaviour: the field, the call, the output
                     -- not "it got confused"
    The evidence     the log line, the stored row, the printed reply, pasted
                     -- not "it worked"

  Delete these comments before you submit.
-->

# Attack 1 — <short name>

**The payload**

```
<the exact text, copied out of the document>
```

**The placement**

<!-- Which file, and where in it. -->

**What the app did**

<!-- The observable behaviour. Name the field, the call, the stored row. -->

**The evidence**

```
<the log line, the stored row, or the printed reply, pasted>
```

**Did it succeed before defences?**  <!-- yes / no -->

---

# Attack 2 — <short name>

**The payload**

```
```

**The placement**

**What the app did**

**The evidence**

```
```

**Did it succeed before defences?**

---

# After the defences

<!-- Re-run both attacks unchanged, against the defended application. Record
     what changed. Be specific about which of them still work, or partly work:
     that honesty is marked here and it is what feeds the
     "what each guardrail does not stop" section of SECURITY.md. -->

| Attack | Before | After | Which guardrail changed it |
|---|---|---|---|
| 1 |  |  |  |
| 2 |  |  |  |

**What still gets through**

<!-- If the answer is "nothing", you have not looked hard enough. Say what you
     did not test, too. -->
