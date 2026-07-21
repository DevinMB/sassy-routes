package routes.sassy;

import com.graphhopper.routing.ev.DecimalEncodedValueImpl;
import com.graphhopper.routing.ev.DefaultImportRegistry;
import com.graphhopper.routing.ev.ImportRegistry;
import com.graphhopper.routing.ev.ImportUnit;

import java.util.Map;

/**
 * DefaultImportRegistry plus the {@code apex_fun} encoded value: our
 * pipeline's fun index (0..1), read from the CSV it exports, baked into every
 * edge at import time. This makes the fun dial route on the exact score the
 * UI displays. Only the IMPORT needs this class — the stock GraphHopper
 * server deserializes encoded values from the finished graph.
 */
public class ApexImportRegistry implements ImportRegistry {
    public static final String KEY = "apex_fun";

    private final DefaultImportRegistry fallback = new DefaultImportRegistry();
    private final Map<Long, Integer> scores;
    private final double defaultFun;

    public ApexImportRegistry(Map<Long, Integer> scores, double defaultFun) {
        this.scores = scores;
        this.defaultFun = defaultFun;
    }

    @Override
    public ImportUnit createImportUnit(String name) {
        if (KEY.equals(name))
            return ImportUnit.create(name,
                    // 7 bits × 0.01 factor → 0.00..1.27, plenty for a 0..1 index
                    props -> new DecimalEncodedValueImpl(KEY, 7, 0.01, false),
                    (lookup, props) -> new ApexFunParser(
                            lookup.getDecimalEncodedValue(KEY), scores, defaultFun));
        return fallback.createImportUnit(name);
    }
}
