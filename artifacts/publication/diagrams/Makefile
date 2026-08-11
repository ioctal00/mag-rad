DOT_FILES := $(wildcard *.dot)
PUML_FILES := $(wildcard *.puml)

DOT_SVGS := $(DOT_FILES:.dot=.svg)
PUML_SVGS := $(PUML_FILES:.puml=.svg)

.PHONY: all graphviz plantuml clean

all: graphviz plantuml

graphviz: $(DOT_SVGS)

plantuml:
	@if ! command -v plantuml >/dev/null 2>&1; then \
		echo "PlantUML nije instaliran. Preskačem .puml renderovanje."; \
	else \
		plantuml -tsvg $(PUML_FILES); \
	fi

%.svg: %.dot
	dot -Tsvg $< -o $@

clean:
	rm -f $(DOT_SVGS) $(PUML_SVGS)
