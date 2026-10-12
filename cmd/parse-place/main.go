// parse-place converts a captured Maps detail payload into the normal Entry schema.
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"

	"github.com/gosom/google-maps-scraper/gmaps"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run() error {
	raw, err := io.ReadAll(io.LimitReader(os.Stdin, 16<<20))
	if err != nil {
		return fmt.Errorf("read payload: %w", err)
	}

	entry, err := gmaps.EntryFromJSON(raw)
	if err != nil {
		return fmt.Errorf("parse payload: %w", err)
	}

	if entry.Title == "" || entry.DataID == "" {
		return fmt.Errorf("payload lacks place identity or title")
	}

	return json.NewEncoder(os.Stdout).Encode(entry)
}
