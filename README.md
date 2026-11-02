# Refund Desk

> **Synthetic.** Everything in this repository is invented to demonstrate [attest](https://github.com/attest-framework/attest): the company, the customers, the orders, the payments and the incidents. No real customer or payment data is used, and no paid model API is called.

Refund Desk is a small customer-support agent, written in Python and TypeScript, that looks up orders, issues refunds and notifies customers. It runs against a scripted OpenAI-compatible model server and a fake payments API, so every run is free and reproducible.

## Role of this repository

| Repo | Role | Tracks |
|---|---|---|
| [`attest-examples`](https://github.com/attest-framework/attest-examples) | One small, copyable example per feature or framework | Latest published release |
| `refund-desk` (this repo) | One end-to-end story: incident → reproduction → fix → blocked regression | attest `main` until 1.0.0, then 1.0.x |

Start with `attest-examples` to copy a working setup for your framework. Read this repository to follow one incident from the first report to a merge gate that blocks its regression.

## License

[Apache-2.0](LICENSE)
