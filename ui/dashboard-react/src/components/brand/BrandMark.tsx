export default function BrandMark() {
  return (
    <div className="flex min-w-0 items-center gap-2.5" aria-label="ayserose">
      <span className="brand-rose-shell grid h-10 w-10 shrink-0 place-items-center overflow-hidden sm:h-11 sm:w-11">
        <img
          src="/ui/assets/brand-rose-violet.png"
          alt=""
          width="44"
          height="44"
          className="h-10 w-10 object-contain sm:h-11 sm:w-11"
          decoding="async"
        />
      </span>
      <span className="truncate text-[15px] font-semibold tracking-[0.08em] text-neutral-100 sm:text-lg sm:tracking-[0.09em]">
        ayserose
      </span>
    </div>
  );
}
