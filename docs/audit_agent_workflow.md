# Audit Agent Workflow (LangGraph Style)

This diagram illustrates the modular, interactive audit workflow for translation and content consistency, designed for a LangGraph agent implementation.

```mermaid
graph TD
    Start([Start])
    Menu{Main Menu}
    ENRepoCheck[English Baseline & Repo Check]
    StructureCheck[HTML Structure Consistency]
    TranslationReview[Translation Content Review]
    IssueFound{Issue Found?}
    Suggestion[Show Suggestion]
    UserChoice{User Choice}
    Accept[Accept]
    Reject[Reject]
    Edit[Edit]
    Back[Back]
    NextPage[Next Page]
    Summary[Summary/Done]

    Start --> Menu
    Menu -->|1| ENRepoCheck
    Menu -->|2| StructureCheck
    Menu -->|3| TranslationReview
    Menu -->|4| Summary
    ENRepoCheck --> IssueFound
    StructureCheck --> IssueFound
    TranslationReview --> IssueFound
    IssueFound -->|Yes| Suggestion
    IssueFound -->|No| NextPage
    Suggestion --> UserChoice
    UserChoice --> Accept
    UserChoice --> Reject
    UserChoice --> Edit
    UserChoice --> Back
    Accept --> NextPage
    Reject --> NextPage
    Edit --> Suggestion
    Back --> Menu
    NextPage -->|More Pages| ENRepoCheck
    NextPage -->|No More| Summary
```

- Each phase is a node; user choices drive navigation.
- Accept, Reject, Edit, and Back are supported at each suggestion.
- The flow supports modular extension and interactive review.
