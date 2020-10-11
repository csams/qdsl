The query DSL with the following optimizations:

* Desugar/compile queries into regular python functions, special casing where possible.
* Generate regular python functions from Boolean ASTs passed to queries. This "compilation" takes microseconds.
* Query the entire flattened tree at once in "find" since it's equivalent to querying individual nodes and accumulating.
* Simplify the where API so we don't need a separate WhereBoolean hierarchy.
* Use tuples instead of lists for values and children. Tuples are slightly smaller.
* Branch "value" defaults to an empty tuple. Since it's a default keyword value, all instances share the same one.
* Use slots for class instance attributes.
* Intern node names so the strings aren't duplicated. This saves a huge amount of memory, especially for things like openshift resources.