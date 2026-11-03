<div class="cover" markdown="1">
<h1 class="nontoc">NEUROSONIC<br>SOURCE CODE EXPLANATION &amp;<br>FACULTY VIVA HANDBOOK</h1>

<p class="sub">How every important source file of the NeuroSonic prototype works, in simple English</p>
<p class="sub">Allwin Raj &nbsp;·&nbsp; Vellore Institute of Technology</p>
<p class="sub">Prepared 3 November 2026 from the actual code in <code>F:\Projects\WOAD-Research\implementation</code></p>

<div class="box" markdown="1">
**How this handbook was made.** Every explanation was written after reading the actual source file. File names,
function names, variable names, constants and line numbers are taken from the code as it is on 3 November 2026.
Numbers in the results sections come from the project's own result files (`outputs/benchmarks/`, test logs).

**Honesty rule.** NeuroSonic is a research prototype, **not a safety device**. It does not measure distance, does not
see in 360 degrees and does not guarantee safe navigation. Physical iPhone and field tests are still pending.
</div>
</div>

[[TOC]]

# How to Use This Handbook

**When the professor points at a file:** go to Part 3 and find that file. Each file has the same seven headings:

1. **Purpose** – what the file is for.
2. **How the code works** – the execution flow, step by step.
3. **Important functions and classes** – input, processing, output, and who calls them.
4. **Important code sections** – the blocks worth showing on screen.
5. **Connections** – which other files it talks to.
6. **Faculty demonstration explanation** – a short paragraph you can say aloud (yellow box).
7. **Possible faculty questions** – with short, correct answers.

**When the professor asks a big-picture question** ("how does the camera reach the AI?", "why the GPU?"), use
Parts 1, 2, 4, 5, 6 and 7. Part 9 explains the most important code line by line. Part 10 is a viva question bank.
Part 11 is a one-page revision sheet to read just before the demonstration.

**Line numbers.** References such as `awareness.py` L205 mean "line 205". In VS Code press `Ctrl+P`, type the file
name, then `Ctrl+G` and the line number.

**Words used in this handbook**

| Term | Simple meaning |
|---|---|
| Backend / server | The Python program on the laptop that does all the work |
| Frontend / client | The web page on the iPhone (HTML, CSS, JavaScript) |
| API endpoint | A web address such as `/api/awareness/frame` that the phone calls to ask the laptop to do something |
| JSON | A text format for structured data, e.g. `{"state": "CLEAR_VIEW"}` |
| Inference | Running a trained AI model on new input to get a prediction |
| Bounding box | A rectangle `[x1, y1, x2, y2]` around a detected object, in pixels |
| Confidence | The model's score between 0 and 1 for a detection |
| CUDA | NVIDIA's software that lets PyTorch run calculations on the graphics card (GPU) |
| FP16 / FP32 | 16-bit ("half") or 32-bit ("full") decimal numbers used inside the network |
| Thread | A separate line of execution inside one program, so several jobs can run at once |
| HTTPS / TLS | Encrypted web connection; iPhones only allow camera, microphone and GPS on HTTPS pages |
