package gmaps

import (
	"math"
	"regexp"
	"strconv"
	"strings"
	"unicode"
)

// Removal-notice statuses distinguish missing notices from unsupported text.
const (
	RemovalNoticeNotPresent   = "not_present"
	RemovalNoticeUnrecognized = "unrecognized"
	RemovalNoticeParsed       = "parsed"
)

var numericReviewDash = regexp.MustCompile(`(\d[0-9,.]*)\s*-\s*(\d[0-9,.]*)`)

func (e *Entry) setReviewRemovalNotice(data []any) {
	e.RemovedReviewsStatus = RemovalNoticeNotPresent
	notices := getNthElementAndCast[[]any](data, 241, 0)

	for i := range notices {
		notice := getNthElementAndCast[[]any](notices, i)
		if getNthElementAndCast[float64](notice, 0) != 3 {
			continue
		}

		e.RemovedReviewsStatus = RemovalNoticeUnrecognized
		body := getNthElementAndCast[[]any](notice, 1)

		for _, index := range []int{0, 3} {
			text := getNthElementAndCast[string](body, index)
			if e.RemovedReviewsNotice == "" {
				e.RemovedReviewsNotice = text
			}

			minReviews, maxReviews := parseRemovedReviewsRange(text)
			if minReviews > 0 {
				e.RemovedReviewsMin, e.RemovedReviewsMax = minReviews, maxReviews
				e.RemovedReviewsNotice = text
				e.RemovedReviewsStatus = RemovalNoticeParsed

				return
			}
		}
	}
}

func parseRemovedReviewsRange(text string) (minimum, maximum int) {
	normalized := strings.Map(func(r rune) rune {
		if unicode.IsSpace(r) {
			return ' '
		}

		if r == '–' || r == '—' || r == '−' {
			return '-'
		}

		return unicode.ToLower(r)
	}, text)
	normalized = numericReviewDash.ReplaceAllString(normalized, "$1 - $2")
	fields := strings.Fields(normalized)

	for i := range fields {
		if i > 0 && (fields[i-1] == "to" || fields[i-1] == "bis" || fields[i-1] == "-") {
			continue
		}

		minReviews, consumed, ok := reviewRangeBound(fields[i:])
		if !ok {
			continue
		}

		end := i + consumed
		if end < len(fields) && (fields[end] == "to" || fields[end] == "bis" || fields[end] == "-") {
			maxReviews, upperConsumed, upperOK := reviewRangeBound(fields[end+1:])
			if upperOK && maxReviews >= minReviews && reviewNounAt(fields, end+1+upperConsumed) {
				return minReviews, maxReviews
			}

			continue
		}

		if !reviewNounAt(fields, end) {
			continue
		}

		if openEndedPrefix(fields[:i]) && minReviews < math.MaxInt {
			return minReviews + 1, 0
		}

		if minReviews == 1 {
			return 1, 1
		}
	}

	return 0, 0
}

func reviewNounAt(fields []string, index int) bool {
	if index >= len(fields) {
		return false
	}

	noun := strings.Trim(fields[index], " ,.;:")

	return noun == "review" || noun == "reviews" || noun == "bewertung" || noun == "bewertungen" ||
		noun == "rezension" || noun == "rezensionen"
}

func openEndedPrefix(fields []string) bool {
	if len(fields) == 0 {
		return false
	}

	last := fields[len(fields)-1]
	if last == "over" || last == "above" || last == "über" || last == "ueber" {
		return true
	}

	if len(fields) < 2 {
		return false
	}

	previous := fields[len(fields)-2]

	return (previous == "more" && last == "than") || (previous == "mehr" && last == "als")
}

func reviewRangeBound(fields []string) (bound, consumed int, valid bool) {
	if len(fields) == 0 {
		return 0, 0, false
	}

	if len(fields) >= 2 {
		if n, ok := parseReviewRangeNumber(fields[0] + " " + fields[1]); ok {
			return n, 2, true
		}
	}

	n, ok := parseReviewRangeNumber(fields[0])

	return n, 1, ok
}

func parseReviewRangeNumber(text string) (int, bool) {
	text = strings.Trim(text, " ,.;:")
	numeric := strings.NewReplacer(",", "", ".", "").Replace(text)

	if n, err := strconv.Atoi(numeric); err == nil {
		return n, n > 0
	}

	words := map[string]int{
		"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
		"six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
		"eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
		"sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
		"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
		"sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
		"ein": 1, "eins": 1, "eine": 1, "zwei": 2, "drei": 3, "vier": 4,
		"fünf": 5, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
		"elf": 11, "zwölf": 12, "zwoelf": 12, "dreizehn": 13, "vierzehn": 14,
		"fünfzehn": 15, "fuenfzehn": 15, "sechzehn": 16, "siebzehn": 17,
		"achtzehn": 18, "neunzehn": 19, "zwanzig": 20, "dreißig": 30, "dreissig": 30,
		"vierzig": 40, "fünfzig": 50, "fuenfzig": 50,
	}
	if n, ok := words[text]; ok {
		return n, true
	}

	parts := strings.Fields(strings.ReplaceAll(text, "-", " "))
	if len(parts) != 2 {
		return 0, false
	}

	tens, tensOK := words[parts[0]]
	units, unitsOK := words[parts[1]]
	ok := tensOK && unitsOK && tens >= 20 && tens%10 == 0 && units > 0 && units < 10

	return tens + units, ok
}

func reviewCountFromPayload(data []any) (int, bool) {
	metrics := getNthElementAndCast[[]any](data, 4)
	if len(metrics) <= 8 {
		return 0, false
	}

	return reviewMetricCount(metrics[8])
}

func reviewHistogramFromPayload(data []any) (map[int]int, bool) {
	histogram := getNthElementAndCast[[]any](data, 175, 3)
	counts := make(map[int]int, 5)
	available := len(histogram) == 5

	for i := range 5 {
		count, present := 0, false
		if i < len(histogram) {
			count, present = reviewMetricCount(histogram[i])
		}

		counts[i+1] = count
		available = available && present
	}

	return counts, available
}

func reviewMetricCount(value any) (int, bool) {
	n, ok := value.(float64)
	if !ok || n < 0 || n >= float64(math.MaxInt) || math.Trunc(n) != n {
		return 0, false
	}

	return int(n), true
}
