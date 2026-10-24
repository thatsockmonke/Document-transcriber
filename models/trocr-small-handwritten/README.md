---
base_model: microsoft/trocr-small-handwritten
library_name: transformers.js
pipeline_tag: image-to-text
tags:
- trocr
---

https://huggingface.co/microsoft/trocr-small-handwritten with ONNX weights to be compatible with Transformers.js.

## Usage (Transformers.js)

If you haven't already, you can install the [Transformers.js](https://huggingface.co/docs/transformers.js) JavaScript library from [NPM](https://www.npmjs.com/package/@xenova/transformers) using:
```bash
npm i @xenova/transformers
```

**Example:** Optical character recognition w/ `Xenova/trocr-small-handwritten`.

```js
import { pipeline } from '@xenova/transformers';

// Create image-to-text pipeline
const captioner = await pipeline('image-to-text', 'Xenova/trocr-small-handwritten');

// Perform optical character recognition
const image = 'https://huggingface.co/datasets/Xenova/transformers.js-docs/resolve/main/handwriting.jpg';
const output = await captioner(image);
// [{ generated_text: 'Mr. Brown commented icily.' }]
```


![image/png](https://cdn-uploads.huggingface.co/production/uploads/61b253b7ac5ecaae3d1efe0c/lin7wLWoBhRhbVt-S9VKw.png)

---

Note: Having a separate repo for ONNX weights is intended to be a temporary solution until WebML gains more traction. If you would like to make your models web-ready, we recommend converting to ONNX using [🤗 Optimum](https://huggingface.co/docs/optimum/index) and structuring your repo like this one (with ONNX weights located in a subfolder named `onnx`).