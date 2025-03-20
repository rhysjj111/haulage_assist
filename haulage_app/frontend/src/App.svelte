<script>
	import Thing from './lib/Thing.svelte';

	let things = $state([
		{ id: 1, name: 'apple' },
		{ id: 2, name: 'banana' },
		{ id: 3, name: 'carrot' },
		{ id: 4, name: 'doughnut' },
		{ id: 5, name: 'egg' }
	]);
</script>

<button class="btn" onclick={() => things.shift()}>
	Remove first thing
</button>

{#each things as thing}
	<Thing name={thing.name} />
{/each}