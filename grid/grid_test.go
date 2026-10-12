package grid_test

import (
	"math"
	"strings"
	"testing"

	"github.com/gosom/google-maps-scraper/grid"
)

func TestPartialEdgeCells(t *testing.T) {
	t.Parallel()

	const kmPerDegree = 111.32

	for _, widthKm := range []float64{0.2, 1.2, 2.1} {
		bbox := grid.BoundingBox{
			MinLat: 48.13, MinLon: 11.57,
			MaxLat: 48.13 + widthKm/kmPerDegree,
		}
		midLat := (bbox.MinLat + bbox.MaxLat) / 2
		bbox.MaxLon = bbox.MinLon + widthKm/(kmPerDegree*math.Cos(midLat*math.Pi/180))
		cells := grid.GenerateCells(bbox, 1)
		expected := int(math.Ceil(widthKm))

		if len(cells) != expected*expected || len(cells) != grid.EstimateCellCount(bbox, 1) {
			t.Fatalf("width %f: expected %d cells, got %d", widthKm, expected*expected, len(cells))
		}

		for _, cell := range cells {
			if cell.Lat <= bbox.MinLat || cell.Lat >= bbox.MaxLat || cell.Lon <= bbox.MinLon || cell.Lon >= bbox.MaxLon {
				t.Fatalf("cell centre outside Munich bounding box: %+v", cell)
			}
		}
	}
}

func TestParseBoundingBox(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name    string
		in      string
		wantErr string
	}{
		{
			name: "valid",
			in:   "40.30,-3.80,40.50,-3.60",
		},
		{
			name:    "invalid min latitude",
			in:      "-91,0,10,10",
			wantErr: "minLat",
		},
		{
			name:    "invalid max longitude",
			in:      "10,0,20,181",
			wantErr: "maxLon",
		},
		{
			name:    "non finite value",
			in:      "NaN,0,10,10",
			wantErr: "must be finite",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()

			_, err := grid.ParseBoundingBox(tc.in)
			if tc.wantErr == "" && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}

			if tc.wantErr != "" {
				if err == nil {
					t.Fatalf("expected error containing %q, got nil", tc.wantErr)
				}

				if !strings.Contains(err.Error(), tc.wantErr) {
					t.Fatalf("expected error containing %q, got %q", tc.wantErr, err.Error())
				}
			}
		})
	}
}

func TestGenerateCellsAndEstimateCellCountNearPoles(t *testing.T) {
	t.Parallel()

	bbox := grid.BoundingBox{
		MinLat: 89.90,
		MinLon: 0.00,
		MaxLat: 89.95,
		MaxLon: 20.00,
	}

	cellSizeKm := 1.0

	gotCells := grid.GenerateCells(bbox, cellSizeKm)
	if len(gotCells) == 0 {
		t.Fatal("expected cells to be generated near poles")
	}

	for _, c := range gotCells {
		if math.IsNaN(c.Lat) || math.IsInf(c.Lat, 0) || math.IsNaN(c.Lon) || math.IsInf(c.Lon, 0) {
			t.Fatalf("expected finite cell coordinates, got %+v", c)
		}
	}

	gotCount := grid.EstimateCellCount(bbox, cellSizeKm)
	if gotCount != len(gotCells) {
		t.Fatalf("expected EstimateCellCount=%d to match generated cells=%d", gotCount, len(gotCells))
	}
}
